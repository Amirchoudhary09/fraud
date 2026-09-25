"""Passwords (PBKDF2-SHA256), JWT access tokens, refresh-token material and TOTP MFA."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

from . import config

_ITERATIONS = 240_000
_secret: str | None = None


# --- passwords -------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


# --- secrets ---------------------------------------------------------------------------

def dev_secret(name: str, factory) -> str:
    """Generated secret persisted in DATA_DIR. Dev/single-instance fallback only: in production
    set the variable from a secrets manager so every replica shares it."""
    path: Path = config.DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(factory())
    return path.read_text().strip()


def _jwt_secret() -> str:
    global _secret
    if config.JWT_SECRET:
        return config.JWT_SECRET
    if _secret is None:
        _secret = dev_secret("jwt_secret.key", lambda: secrets.token_urlsafe(48))
    return _secret


# --- tokens ----------------------------------------------------------------------------

def create_access_token(user: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=config.ACCESS_TOKEN_MINUTES)
    return jwt.encode({"sub": str(user["id"]), "role": user["role"], "typ": "access", "exp": exp},
                      _jwt_secret(), algorithm="HS256")


def create_mfa_token(user: dict) -> str:
    """Short-lived proof that the password step passed; exchanged for tokens with a TOTP code."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode({"sub": str(user["id"]), "typ": "mfa", "exp": exp}, _jwt_secret(), algorithm="HS256")


def decode_token(token: str, typ: str = "access") -> dict | None:
    try:
        claims = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return claims if claims.get("typ") == typ else None


def new_refresh_token() -> tuple[str, str]:
    """Returns (token for the client, SHA-256 digest to store). The raw token is never stored."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# --- TOTP (RFC 6238, SHA-1, 30 s, 6 digits: works with Google Authenticator etc.) -------

def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret_b32: str, at: float | None = None) -> str:
    return _hotp(secret_b32, int((at or time.time()) // 30))


def verify_totp(secret_b32: str, code: str, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    step = int(time.time() // 30)
    return any(hmac.compare_digest(_hotp(secret_b32, step + d), code) for d in range(-window, window + 1))


def totp_uri(secret_b32: str, email: str, issuer: str = "IdentityEvidence") -> str:
    return f"otpauth://totp/{issuer}:{email}?secret={secret_b32}&issuer={issuer}&digits=6&period=30"
