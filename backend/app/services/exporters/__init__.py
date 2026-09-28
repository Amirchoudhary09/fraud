"""Audit-log exporters (SIEM, WORM object storage).

Each exporter ships audit events after its own cursor (stored in the kv table), in seq order,
and advances the cursor only after the destination accepted the batch: at-least-once
delivery, nothing skipped. Exports run on a background thread; with Redis configured, a
lock makes sure only one replica exports at a time.
"""
import logging
import threading

from ...core import audit_store, config, redis_client
from ...core.database import now
from ...repositories import kv
from .base import Exporter
from .siem import SiemExporter
from .worm import WormExporter

log = logging.getLogger(__name__)

EXPORTERS: list[Exporter] = [SiemExporter(), WormExporter()]


def _cursor_key(name: str) -> str:
    return f"export:{name}:cursor"


def status() -> list[dict]:
    head = audit_store.head_seq()
    out = []
    for e in EXPORTERS:
        cur = kv.get(_cursor_key(e.name), 0)
        out.append({"name": e.name, "enabled": e.enabled(), "destination": e.describe(), "cursor": cur,
                    "head_seq": head, "lag": head - cur if e.enabled() else None,
                    **kv.get(f"export:{e.name}:status", {})})
    return out


def run_once(exporter: Exporter, max_batches: int = 20) -> int:
    """Ships pending events. Returns how many were delivered. Raises nothing: errors are recorded."""
    if not exporter.enabled():
        return 0
    shipped = 0
    try:
        for _ in range(max_batches):
            cur = kv.get(_cursor_key(exporter.name), 0)
            events = audit_store.after(cur, exporter.batch_size)
            if not events:
                break
            exporter.ship(events)
            kv.set(_cursor_key(exporter.name), events[-1]["seq"])
            shipped += len(events)
        kv.set(f"export:{exporter.name}:status", {"last_success": now(), "last_error": None})
    except Exception as e:
        log.warning("%s export failed: %s", exporter.name, e)
        kv.set(f"export:{exporter.name}:status", {"last_error": f"{type(e).__name__}: {str(e)[:300]}",
                                                   "last_error_at": now()})
    return shipped


def run_all():
    r = redis_client.get()
    for e in EXPORTERS:
        if not e.enabled():
            continue
        if r is not None and not r.set(f"ie:lock:export:{e.name}", "1", nx=True, ex=config.EXPORT_INTERVAL * 4):
            continue  # another replica is exporting
        try:
            run_once(e)
        finally:
            if r is not None:
                r.delete(f"ie:lock:export:{e.name}")


_stop = threading.Event()
_thread: threading.Thread | None = None


def start():
    global _thread
    if _thread or config.JOBS_INLINE or not any(e.enabled() for e in EXPORTERS):
        return
    _stop.clear()

    def loop():
        while not _stop.wait(config.EXPORT_INTERVAL):
            run_all()

    _thread = threading.Thread(target=loop, name="audit-exporter", daemon=True)
    _thread.start()


def stop():
    global _thread
    _stop.set()
    if _thread:
        _thread.join(timeout=5)
    _thread = None
