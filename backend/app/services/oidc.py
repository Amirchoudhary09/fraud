"""OpenID Connect single sign-on (authorization code flow + PKCE, confidential client).

start():    creates a one-time state bound to a nonce and a PKCE verifier (10 min TTL) and returns
            the IdP authorization URL.
callback(): consumes the state (single use), exchanges the code with the PKCE verifier and client
            secret, then verifies the id_token: signature against the IdP's JWKS, issuer,
            audience, expiry, nonce, verified email and allowed email domain.

Works with any OIDC provider: Google Workspace, Microsoft Entra ID, Okta, Auth0, Keycloak.
"""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt

from ..core import config
from ..repositories import kv

STATE_TTL = 600
_http = httpx.Client(timeout=15)
_discovery: dict | None = None


class OidcError(ValueError):
    pass


def enabled() -> bool:
    return bool(config.OIDC_ISSUER and config.OIDC_CLIENT_ID and config.OIDC_CLIENT_SECRET and config.OIDC_REDIRECT_URI)


def set_http_client(client: httpx.Client):
    """Tests inject a client with a mock transport."""
    global _http, _discovery
    _http, _discovery = client, None


def discovery() -> dict:
    global _discovery
    if _discovery is None:
        url = config.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
        r = _http.get(url)
        r.raise_for_status()
        d = r.json()
        if d.get("issuer", "").rstrip("/") != config.OIDC_ISSUER.rstrip("/"):
            raise OidcError("Discovery document issuer does not match OIDC_ISSUER")
        _discovery = d
    return _discovery


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def start() -> str:
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    kv.set(f"oidc:state:{state}", {"nonce": nonce, "verifier": verifier, "exp": time.time() + STATE_TTL})
    params = {
        "response_type": "code", "client_id": config.OIDC_CLIENT_ID, "redirect_uri": config.OIDC_REDIRECT_URI,
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
    }
    return discovery()["authorization_endpoint"] + "?" + urlencode(params)


def _consume_state(state: str) -> dict:
    data = kv.pop(f"oidc:state:{state}")  # single use, even if the rest of the callback fails
    if not data or data["exp"] < time.time():
        raise OidcError("Sign-in link expired or already used. Please try again.")
    return data


def _signing_key(token: str):
    header = jwt.get_unverified_header(token)
    r = _http.get(discovery()["jwks_uri"])
    r.raise_for_status()
    for k in r.json().get("keys", []):
        if k.get("kid") == header.get("kid"):
            return jwt.PyJWK(k).key
    raise OidcError("id_token signed with an unknown key")


def callback(code: str, state: str) -> dict:
    """Returns verified claims: {sub, email, name, amr}."""
    st = _consume_state(state)
    d = discovery()
    r = _http.post(d["token_endpoint"], data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": config.OIDC_REDIRECT_URI,
        "client_id": config.OIDC_CLIENT_ID, "client_secret": config.OIDC_CLIENT_SECRET,
        "code_verifier": st["verifier"],
    })
    if r.status_code != 200:
        raise OidcError(f"Token exchange failed (HTTP {r.status_code})")
    id_token = r.json().get("id_token")
    if not id_token:
        raise OidcError("IdP returned no id_token")
    try:
        claims = jwt.decode(id_token, _signing_key(id_token), algorithms=["RS256", "ES256", "PS256"],
                            audience=config.OIDC_CLIENT_ID, issuer=d["issuer"],
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]}, leeway=60)
    except jwt.PyJWTError as e:
        raise OidcError(f"Invalid id_token: {e}") from e
    if claims.get("nonce") != st["nonce"]:
        raise OidcError("id_token nonce mismatch")
    email = str(claims.get("email", "")).lower()
    if not email or claims.get("email_verified") is False:
        raise OidcError("The identity provider did not return a verified email address")
    if config.OIDC_ALLOWED_DOMAINS and email.rsplit("@", 1)[-1] not in config.OIDC_ALLOWED_DOMAINS:
        raise OidcError("Your email domain is not allowed to sign in here")
    amr = claims.get("amr") or []
    if config.OIDC_REQUIRE_MFA and not ({"mfa", "otp", "hwk", "swk", "fido"} & set(amr)):
        raise OidcError("Your organisation requires multi-factor sign-in at the identity provider")
    return {"sub": claims["sub"], "email": email, "name": claims.get("name"), "amr": json.dumps(amr)}
