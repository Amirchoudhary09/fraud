"""Append-only, tamper-evident audit log (the security/audit plane).

- Kept apart from application data: its own SQLite file (AUDIT_DB_PATH) or its own PostgreSQL
  database (AUDIT_DATABASE_URL), so app code and retention jobs never touch it.
- Database triggers reject UPDATE and DELETE (and TRUNCATE on PostgreSQL): events can only be appended.
- Every event stores prev_hash and hash = SHA-256(prev_hash + canonical JSON of the event).
  Changing or removing any past event breaks the chain, which verify() detects.
- Appends are serialised (a write lock on SQLite, an advisory transaction lock on PostgreSQL),
  so several API replicas/workers can write without forking the chain.
- Every event is also appended to a local JSONL mirror; the WORM/SIEM exporters ship the log off-host.
- Sensitive values are not copied in: IPs are salted hashes, search inputs are referenced
  by search id instead of being duplicated.
"""
import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone

from . import config, context
from .database import is_postgres, open_db

GENESIS = "0" * 64
_lock = threading.Lock()
_ADVISORY_KEY = 7_411_902_001  # arbitrary constant: "audit chain append"

_COLUMNS = """
    event_id TEXT NOT NULL UNIQUE,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_user_id INTEGER,
    target_type TEXT,
    target_id TEXT,
    case_id TEXT,
    search_id TEXT,
    request_id TEXT,
    ip_hash TEXT,
    result TEXT NOT NULL,
    detail TEXT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_search ON audit_events(search_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events(actor_user_id, ts)",
    "CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events(event_type, ts)",
]

SQLITE_SCHEMA = [
    f"CREATE TABLE IF NOT EXISTS audit_events (seq INTEGER PRIMARY KEY AUTOINCREMENT,{_COLUMNS})",
    *_INDEXES,
    "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events "
    "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
]

POSTGRES_SCHEMA = [
    f"CREATE TABLE IF NOT EXISTS audit_events (seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,{_COLUMNS})",
    *_INDEXES,
    "CREATE OR REPLACE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS "
    "$$ BEGIN RAISE EXCEPTION 'audit log is append-only'; END $$",
    "DROP TRIGGER IF EXISTS audit_no_update ON audit_events",
    "CREATE TRIGGER audit_no_update BEFORE UPDATE OR DELETE ON audit_events "
    "FOR EACH ROW EXECUTE FUNCTION audit_append_only()",
    "DROP TRIGGER IF EXISTS audit_no_truncate ON audit_events",
    "CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events "
    "FOR EACH STATEMENT EXECUTE FUNCTION audit_append_only()",
]

FIELDS = ("event_id", "ts", "event_type", "actor_user_id", "target_type", "target_id", "case_id",
          "search_id", "request_id", "ip_hash", "result", "detail")


def target():
    return config.AUDIT_DATABASE_URL or config.AUDIT_DB_PATH


def _db():
    return open_db(target(), _lock)


def init():
    with _db() as c:
        for stmt in (POSTGRES_SCHEMA if is_postgres(target()) else SQLITE_SCHEMA):
            c.execute(stmt)


def compute_hash(prev_hash: str, event: dict) -> str:
    body = json.dumps({k: event.get(k) for k in FIELDS}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def append(event_type: str, *, target_type: str | None = None, target_id: str | None = None,
           case_id: str | None = None, search_id: str | None = None, result: str = "SUCCESS",
           detail: dict | str | None = None, actor_user_id: int | None = None) -> dict:
    event = {
        "event_id": "EVT-" + uuid.uuid4().hex[:16],
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "event_type": event_type,
        "actor_user_id": actor_user_id if actor_user_id is not None else context.actor_id.get(),
        "target_type": target_type, "target_id": target_id, "case_id": case_id, "search_id": search_id,
        "request_id": context.request_id.get(), "ip_hash": context.ip_hash.get(), "result": result,
        "detail": (json.dumps(detail, sort_keys=True) if isinstance(detail, dict) else detail)[:2000] if detail else None,
    }
    cols = FIELDS + ("prev_hash", "hash")
    with _db() as c:
        if is_postgres(target()):
            c.execute("SELECT pg_advisory_xact_lock(?)", (_ADVISORY_KEY,))  # serialise appends across replicas
        else:
            c.execute("BEGIN IMMEDIATE")  # serialise appends across processes sharing the file
        row = c.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        event["prev_hash"] = row["hash"] if row else GENESIS
        event["hash"] = compute_hash(event["prev_hash"], event)
        c.execute(f"INSERT INTO audit_events ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                  tuple(event[k] for k in cols))
    config.AUDIT_MIRROR_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.AUDIT_MIRROR_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def _rows(sql: str, args=()) -> list[dict]:
    with _db() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def query(*, case_id: str | None = None, actor_user_id: int | None = None, event_types: list[str] | None = None,
          since: str | None = None, target_id: str | None = None, limit: int = 200) -> list[dict]:
    where, args = [], []
    for col, val in (("case_id", case_id), ("actor_user_id", actor_user_id), ("target_id", target_id)):
        if val is not None:
            where.append(f"{col} = ?")
            args.append(val)
    if event_types:
        where.append(f"event_type IN ({', '.join('?' * len(event_types))})")
        args += event_types
    if since:
        where.append("ts >= ?")
        args.append(since)
    sql = "SELECT * FROM audit_events" + (" WHERE " + " AND ".join(where) if where else "")
    return _rows(sql + " ORDER BY seq DESC LIMIT ?", (*args, limit))


def after(seq: int, limit: int = 500) -> list[dict]:
    """Events with seq > given seq, oldest first (for export to SIEM / WORM storage)."""
    return _rows("SELECT * FROM audit_events WHERE seq > ? ORDER BY seq LIMIT ?", (seq, limit))


def head_seq() -> int:
    with _db() as c:
        return c.execute("SELECT COALESCE(MAX(seq), 0) FROM audit_events").fetchone()[0]


def for_case(case_id: str, search_ids: list[str], limit: int = 2000) -> list[dict]:
    """Every event of a case, including the per-step events of searches run inside it (oldest first)."""
    sql = "SELECT * FROM audit_events WHERE case_id = ?"
    if search_ids:
        sql += f" OR search_id IN ({', '.join('?' * len(search_ids))})"
    return _rows(sql + " ORDER BY seq LIMIT ?", (case_id, *search_ids, limit))


def count(*, event_types: list[str], since: str, actor_user_id: int | None = None, ip_hash: str | None = None,
          distinct: str | None = None) -> int:
    if distinct not in (None, "target_id", "actor_user_id", "ip_hash"):
        raise ValueError("unsupported distinct column")
    where = [f"event_type IN ({', '.join('?' * len(event_types))})", "ts >= ?"]
    args: list = [*event_types, since]
    if actor_user_id is not None:
        where.append("actor_user_id = ?")
        args.append(actor_user_id)
    if ip_hash is not None:
        where.append("ip_hash = ?")
        args.append(ip_hash)
    what = f"COUNT(DISTINCT {distinct})" if distinct else "COUNT(*)"
    with _db() as c:
        return c.execute(f"SELECT {what} FROM audit_events WHERE {' AND '.join(where)}", args).fetchone()[0]


def verify() -> dict:
    """Walks the whole chain. Returns ok=False with the first broken event if tampered."""
    prev, n = GENESIS, 0
    with _db() as c:
        for r in c.execute("SELECT * FROM audit_events ORDER BY seq").fetchall():
            e = dict(r)
            if e["prev_hash"] != prev or compute_hash(prev, e) != e["hash"]:
                return {"ok": False, "events_checked": n, "broken_at": e["event_id"], "seq": e["seq"]}
            prev, n = e["hash"], n + 1
    return {"ok": True, "events_checked": n, "head_hash": prev}
