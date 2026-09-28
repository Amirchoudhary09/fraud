"""OIDC SSO against a fake identity provider (RSA-signed id_tokens, JWKS, discovery, token endpoint)."""
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import config
from app.services import oidc

ISSUER = "https://idp.test"
CLIENT = "ie-client"


class FakeIdP:
    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims: dict = {}
        self.last_token_request: dict = {}

    def jwks(self):
        pub = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**pub, "kid": "k1", "use": "sig", "alg": "RS256"}]}

    def id_token(self, nonce: str, key=None, **override) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT, "sub": "idp-user-1", "email": "sso.user@corp.test",
                  "email_verified": True, "iat": now, "exp": now + 300, "nonce": nonce, "amr": ["pwd", "mfa"],
                  **self.claims, **override}
        return jwt.encode(claims, key or self.key, algorithm="RS256", headers={"kid": "k1"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                                             "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks"})
        if path == "/jwks":
            return httpx.Response(200, json=self.jwks())
        if path == "/token":
            form = parse_qs(request.content.decode())
            self.last_token_request = {k: v[0] for k, v in form.items()}
            return httpx.Response(200, json={"id_token": self.next_token, "access_token": "x", "token_type": "Bearer"})
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch, client, admin_h):
    fake = FakeIdP()
    for k, v in {"OIDC_ISSUER": ISSUER, "OIDC_CLIENT_ID": CLIENT, "OIDC_CLIENT_SECRET": "s3cret",
                 "OIDC_REDIRECT_URI": "https://app.test/bff/oidc/callback", "OIDC_DEFAULT_ROLE": "user",
                 "OIDC_ALLOWED_DOMAINS": ["corp.test"], "OIDC_REQUIRE_MFA": True}.items():
        monkeypatch.setattr(config, k, v)
    oidc.set_http_client(httpx.Client(transport=httpx.MockTransport(fake.handler)))
    yield fake
    oidc.set_http_client(httpx.Client(timeout=15))


def begin(client) -> tuple[str, str, dict]:
    url = client.post("/api/auth/oidc/start").json()["authorization_url"]
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    return q["state"], q["nonce"], q


def finish(client, idp, state, nonce, **token_overrides):
    idp.next_token = idp.id_token(nonce, **token_overrides)
    return client.post("/api/auth/oidc/callback", json={"code": "auth-code", "state": state})


def test_status_advertises_sso(client, idp):
    assert client.get("/api/auth/status").json()["sso"] == {"enabled": True, "name": "SSO"}


def test_sso_happy_path_with_pkce(client, idp):
    state, nonce, q = begin(client)
    assert q["code_challenge_method"] == "S256" and q["client_id"] == CLIENT and q["scope"] == "openid email profile"
    r = finish(client, idp, state, nonce)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "sso.user@corp.test" and r.json()["user"]["role"] == "user"
    # PKCE: the verifier sent to the token endpoint hashes to the challenge in the authorize URL
    import base64
    import hashlib
    v = idp.last_token_request["code_verifier"]
    assert base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode() == q["code_challenge"]
    assert idp.last_token_request["client_secret"] == "s3cret"


def test_state_is_single_use(client, idp):
    state, nonce, _ = begin(client)
    assert finish(client, idp, state, nonce).status_code == 200
    r = finish(client, idp, state, nonce)
    assert r.status_code == 401 and "expired or already used" in r.json()["detail"]


@pytest.mark.parametrize("override,expect", [
    ({"nonce": "wrong"}, "nonce"),
    ({"aud": "other-client"}, "audience"),
    ({"iss": "https://evil.test"}, "issuer"),
    ({"exp": int(time.time()) - 3600}, "expired"),
    ({"email": "someone@gmail.com"}, "domain"),
    ({"email_verified": False}, "verified email"),
    ({"amr": ["pwd"]}, "multi-factor"),
])
def test_rejects_bad_id_tokens(client, idp, override, expect):
    state, nonce, _ = begin(client)
    if "nonce" in override:
        idp.next_token = idp.id_token(override["nonce"])
        r = client.post("/api/auth/oidc/callback", json={"code": "c", "state": state})
    else:
        r = finish(client, idp, state, nonce, **override)
    assert r.status_code == 401 and expect in r.json()["detail"].lower(), r.text


def test_rejects_token_signed_by_other_key(client, idp):
    state, nonce, _ = begin(client)
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    idp.next_token = idp.id_token(nonce, key=attacker)
    r = client.post("/api/auth/oidc/callback", json={"code": "c", "state": state})
    assert r.status_code == 401 and "signature" in r.json()["detail"].lower()


def test_subject_cannot_take_over_another_account(client, idp, admin_h):
    state, nonce, _ = begin(client)
    assert finish(client, idp, state, nonce, sub="idp-user-9", email="owner9@corp.test").status_code == 200
    # later the IdP reports the same subject with another existing user's email
    state, nonce, _ = begin(client)
    client.post("/api/users", json={"email": "victim@corp.test", "password": "victim-pass-123", "role": "investigator"},
                headers=admin_h)
    r = finish(client, idp, state, nonce, sub="idp-user-9", email="victim@corp.test")
    assert r.status_code == 401 and "different account" in r.json()["detail"]


def test_sso_not_configured_returns_404(client, monkeypatch):
    monkeypatch.setattr(config, "OIDC_ISSUER", "")
    assert client.post("/api/auth/oidc/start").status_code == 404
