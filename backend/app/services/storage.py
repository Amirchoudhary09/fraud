"""Encrypted evidence file storage on local disk (UPLOAD_DIR). Files are encrypted at rest with
the evidence key; their SHA-256 is taken on the plaintext before encryption.
Swap save/load/remove for an S3 client (with SSE-KMS + object lock) to move storage off-server."""
from pathlib import Path

from ..core import config, crypto

ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "application/pdf": ".pdf",
                 "text/plain": ".txt"}


def check(data: bytes, content_type: str):
    if content_type not in ALLOWED_TYPES:
        raise ValueError(f"File type {content_type or 'unknown'} not allowed. Use PNG, JPEG, WEBP, PDF or TXT.")
    if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValueError(f"File is larger than {config.MAX_UPLOAD_MB} MB.")


def save(object_id: str, data: bytes) -> str:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = config.UPLOAD_DIR / f"{object_id}.enc"
    path.write_bytes(crypto.encrypt(data))
    return str(path)


def load(path: str) -> bytes:
    return crypto.decrypt(Path(path).read_bytes())


def remove(path: str):
    Path(path).unlink(missing_ok=True)
