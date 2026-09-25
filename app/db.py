import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued | running | done | failed
    stage TEXT NOT NULL,
    purpose TEXT NOT NULL,
    provider TEXT NOT NULL,
    input_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    investigation_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    investigation_id TEXT,
    client TEXT,
    detail TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(config.DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init():
    with connect() as c:
        c.executescript(SCHEMA)


def audit(action: str, investigation_id: str | None = None, client: str | None = None, detail: str = ""):
    with connect() as c:
        c.execute("INSERT INTO audit_log (ts, action, investigation_id, client, detail) VALUES (?,?,?,?,?)",
                  (now(), action, investigation_id, client, detail[:1000]))


def create_investigation(input_data: dict, purpose: str, provider: str) -> str:
    inv_id = uuid.uuid4().hex[:12]
    ts = now()
    with connect() as c:
        c.execute("INSERT INTO investigations (id, created_at, updated_at, status, stage, purpose, provider, input_json)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (inv_id, ts, ts, "queued", "Queued", purpose, provider, json.dumps(input_data)))
    return inv_id


def update_investigation(inv_id: str, **fields):
    if "result" in fields:
        fields["result_json"] = json.dumps(fields.pop("result"))
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as c:
        c.execute(f"UPDATE investigations SET {cols} WHERE id = ?", (*fields.values(), inv_id))


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["input"] = json.loads(d.pop("input_json"))
    rj = d.pop("result_json", None)
    d["result"] = json.loads(rj) if rj else None
    return d


def get_investigation(inv_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM investigations WHERE id = ?", (inv_id,)).fetchone()
    return _row(r) if r else None


def list_investigations(limit: int = 50) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT id, created_at, status, stage, purpose, provider, input_json FROM investigations"
                         " ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]


def add_feedback(inv_id: str, candidate_id: str, verdict: str, note: str | None):
    with connect() as c:
        c.execute("INSERT INTO feedback (created_at, investigation_id, candidate_id, verdict, note) VALUES (?,?,?,?,?)",
                  (now(), inv_id, candidate_id, verdict, note))


def get_feedback(inv_id: str) -> dict[str, str]:
    """Latest verdict per candidate."""
    with connect() as c:
        rows = c.execute("SELECT candidate_id, verdict FROM feedback WHERE investigation_id = ? ORDER BY id",
                         (inv_id,)).fetchall()
    return {r["candidate_id"]: r["verdict"] for r in rows}


def delete_investigation(inv_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM investigations WHERE id = ?", (inv_id,))
        c.execute("DELETE FROM feedback WHERE investigation_id = ?", (inv_id,))
    return cur.rowcount > 0
