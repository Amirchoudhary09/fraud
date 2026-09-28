"""Job queue: API requests enqueue work and return immediately; workers run it.

Two backends, same interface (submit / start / stop):
- In-process threads (default). Correct for ONE API replica; jobs are lost on restart.
- Redis (REDIS_URL set): a reliable queue shared by any number of API replicas. Jobs are
  executed by `python -m app.workers.worker` processes (a separate Railway service), and a job
  held by a crashed worker is re-queued once that worker's heartbeat expires.

Jobs are referenced by name with JSON arguments, so they can cross process boundaries.
"""
import json
import logging
import queue
import socket
import threading
import time
import uuid

from ..agents.supervisor import run_investigation
from ..core import config, redis_client
from ..repositories import searches
from ..schemas.identity import IdentityInput

log = logging.getLogger(__name__)

QUEUE = "ie:jobs"
PROCESSING = "ie:processing:"   # + worker id  (list of jobs that worker holds)
HEARTBEAT = "ie:heartbeat:"     # + worker id  (key with TTL)
HEARTBEAT_TTL = 30


def _run_search(search_id: str, identity: dict, user_id: int | None, request_id: str | None, ip_hash: str | None,
                mode: str = "standard"):
    run_investigation(search_id, IdentityInput(**identity), user_id, request_id, ip_hash, mode=mode)


REGISTRY = {"run_search": _run_search}


def execute(raw: str):
    job = json.loads(raw)
    fn = REGISTRY[job["name"]]
    fn(*job["args"])


# --- submit ------------------------------------------------------------------------------

_q: "queue.Queue[str | None]" = queue.Queue()
_threads: list[threading.Thread] = []


def submit(name: str, *args):
    if name not in REGISTRY:
        raise KeyError(name)
    raw = json.dumps({"id": uuid.uuid4().hex, "name": name, "args": list(args), "enqueued_at": time.time()})
    if config.JOBS_INLINE:
        execute(raw)
        return
    r = redis_client.get()
    if r is not None:
        r.lpush(QUEUE, raw)
    else:
        _q.put(raw)


# --- in-process backend -------------------------------------------------------------------

def _thread_worker():
    while True:
        raw = _q.get()
        if raw is None:
            break
        try:
            execute(raw)
        except Exception:
            log.exception("job failed: %s", raw[:200])
        finally:
            _q.task_done()


def start():
    """Starts in-process workers, unless jobs run inline or on Redis workers."""
    if config.JOBS_INLINE or _threads or redis_client.get() is not None:
        return
    for i in range(max(1, config.WORKERS)):
        t = threading.Thread(target=_thread_worker, name=f"job-worker-{i}", daemon=True)
        t.start()
        _threads.append(t)


def stop():
    for _ in _threads:
        _q.put(None)
    for t in _threads:
        t.join(timeout=5)
    _threads.clear()


def fail_interrupted():
    """In-memory jobs are lost when the process stops; Redis jobs survive and are left alone."""
    if redis_client.get() is None:
        searches.fail_unfinished("Interrupted by a server restart. Please run it again.")


# --- Redis worker -------------------------------------------------------------------------

class RedisWorker:
    def __init__(self, r, worker_id: str | None = None):
        self.r = r
        self.id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
        self.processing = PROCESSING + self.id

    def heartbeat(self):
        self.r.set(HEARTBEAT + self.id, "1", ex=HEARTBEAT_TTL)

    def recover_orphans(self) -> int:
        """Moves jobs held by workers whose heartbeat expired back onto the queue."""
        moved = 0
        for key in self.r.scan_iter(PROCESSING + "*"):
            wid = key[len(PROCESSING):]
            if wid == self.id or self.r.exists(HEARTBEAT + wid):
                continue
            while self.r.lmove(key, QUEUE, "RIGHT", "LEFT"):
                moved += 1
        if moved:
            log.warning("re-queued %d job(s) from dead workers", moved)
        return moved

    def run_once(self, timeout: int = 5) -> bool:
        """Processes at most one job. Returns False when the queue was empty."""
        self.heartbeat()
        raw = self.r.blmove(QUEUE, self.processing, timeout, "RIGHT", "LEFT")
        if raw is None:
            return False
        try:
            execute(raw)
        except Exception:
            log.exception("job failed: %s", raw[:200])
        finally:
            self.r.lrem(self.processing, 1, raw)
        return True

    def run_forever(self):
        log.info("worker %s started", self.id)
        last_sweep = 0.0
        while True:
            if time.time() - last_sweep > HEARTBEAT_TTL:
                self.recover_orphans()
                last_sweep = time.time()
            self.run_once()
