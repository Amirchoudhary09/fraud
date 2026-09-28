"""Sliding-window rate limiter. Uses a Redis sorted set per key when REDIS_URL is set (shared by
all API replicas); otherwise an in-memory window (single replica only)."""
import threading
import time
import uuid
from collections import defaultdict, deque

from fastapi import HTTPException

from . import redis_client

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _too_many():
    raise HTTPException(429, "Rate limit reached. Try again later.")


def check(key: str, limit: int, window: int = 3600):
    r = redis_client.get()
    if r is not None:
        _check_redis(r, key, limit, window)
        return
    t = time.time()
    with _lock:
        q = _hits[key]
        while q and t - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            _too_many()
        q.append(t)


def _check_redis(r, key: str, limit: int, window: int):
    now = time.time()
    rkey, member = f"ie:rl:{key}", f"{now}:{uuid.uuid4().hex[:8]}"
    pipe = r.pipeline(transaction=True)
    pipe.zremrangebyscore(rkey, 0, now - window)
    pipe.zadd(rkey, {member: now})
    pipe.zcard(rkey)
    pipe.expire(rkey, window)
    count = pipe.execute()[2]
    if count > limit:
        r.zrem(rkey, member)  # rejected attempts do not consume the window
        _too_many()
