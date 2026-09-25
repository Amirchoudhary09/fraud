"""In-memory sliding-window rate limiter (per client key). Single-instance only;
use Redis for this once the API runs on more than one replica."""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def check(key: str, limit: int, window: int = 3600):
    t = time.time()
    with _lock:
        q = _hits[key]
        while q and t - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Rate limit reached. Try again later.")
        q.append(t)
