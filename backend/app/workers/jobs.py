"""Job queue: API requests enqueue work and return immediately; worker threads run it.

The API never waits for search/LLM calls; the frontend polls the investigation's `stage`.
This in-process queue suits one instance. With several replicas, replace submit() with a
Redis-backed queue (RQ/Celery) and run the same job functions in separate worker processes.
"""
import logging
import queue
import threading

from ..core import config
from ..repositories import searches

log = logging.getLogger(__name__)

_q: "queue.Queue[tuple | None]" = queue.Queue()
_threads: list[threading.Thread] = []


def _worker():
    while True:
        job = _q.get()
        if job is None:
            break
        fn, args = job
        try:
            fn(*args)
        except Exception:
            log.exception("job %s failed", getattr(fn, "__name__", fn))
        finally:
            _q.task_done()


def start():
    if config.JOBS_INLINE or _threads:
        return
    for i in range(max(1, config.WORKERS)):
        t = threading.Thread(target=_worker, name=f"job-worker-{i}", daemon=True)
        t.start()
        _threads.append(t)


def stop():
    for _ in _threads:
        _q.put(None)
    for t in _threads:
        t.join(timeout=5)
    _threads.clear()


def submit(fn, *args):
    if config.JOBS_INLINE:
        fn(*args)
    else:
        _q.put((fn, args))


def fail_interrupted():
    """Jobs live in memory, so anything queued/running when the process stopped is lost."""
    searches.fail_unfinished("Interrupted by a server restart. Please run it again.")
