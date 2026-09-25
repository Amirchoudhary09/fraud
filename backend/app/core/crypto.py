"""Application-level encryption at rest for evidence content and files (Fernet: AES-128-CBC +
HMAC-SHA256). Integrity hashes are always computed on the plaintext, so they can be
re-verified after decryption. In production, EVIDENCE_KEY should come from a KMS/secrets manager."""
from cryptography.fernet import Fernet

from . import config
from .security import dev_secret

_fernet: Fernet | None = None


def _f() -> Fernet:
    global _fernet
    if _fernet is None:
        key = config.EVIDENCE_KEY or dev_secret("evidence.key", lambda: Fernet.generate_key().decode())
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt(data: bytes) -> bytes:
    return _f().encrypt(data)


def decrypt(token: bytes) -> bytes:
    return _f().decrypt(token)


def encrypt_text(text: str) -> str:
    return encrypt(text.encode()).decode()


def decrypt_text(token: str) -> str:
    return decrypt(token.encode()).decode()
