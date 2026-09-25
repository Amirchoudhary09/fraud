"""Per-request context (request id, hashed client IP, acting user) for audit events.

Set by the HTTP middleware and the auth dependency; background jobs set it explicitly so
events they emit are still attributed to the user who started the work.
"""
import hashlib
import uuid
from contextvars import ContextVar

from . import config

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
ip_hash: ContextVar[str | None] = ContextVar("ip_hash", default=None)
actor_id: ContextVar[int | None] = ContextVar("actor_id", default=None)


def new_request_id() -> str:
    return "REQ-" + uuid.uuid4().hex[:16]


def hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(f"{config.IP_HASH_SALT}:{ip}".encode()).hexdigest()[:24]


def bind(req_id: str | None = None, user_id: int | None = None, ip: str | None = None):
    """Used by background jobs to carry the originating request's context."""
    request_id.set(req_id or new_request_id())
    if user_id is not None:
        actor_id.set(user_id)
    if ip is not None:
        ip_hash.set(ip)
