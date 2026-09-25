"""Search history (spec section 6): one row per search, separate from the audit log."""
import json
import sqlite3

from ..core.database import connect, dumps, loads, new_id, now

_LIST_COLS = ("id, user_id, case_id, incident_id, entity_id, search_type, query_json, normalized_query, purpose,"
              " provider, status, stage, candidate_count, created_at, started_at, completed_at")


def normalize(query: dict) -> str:
    return " | ".join(f"{k}={' '.join(str(v).lower().split())}" for k, v in sorted(query.items()) if v)


def create(query: dict, purpose: str, provider: str, user_id: int, search_type: str = "PUBLIC_IDENTITY",
           case_id: str | None = None, incident_id: str | None = None, entity_id: str | None = None) -> str:
    sid, ts = new_id("SRCH"), now()
    with connect() as c:
        c.execute("INSERT INTO searches (id, user_id, case_id, incident_id, entity_id, search_type, query_json,"
                  " normalized_query, purpose, provider, status, stage, created_at, updated_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, user_id, case_id, incident_id, entity_id, search_type, json.dumps(query), normalize(query),
                   purpose, provider, "queued", "Queued", ts, ts))
    return sid


def update(search_id: str, **fields):
    if "result" in fields:
        fields["result_json"] = dumps(fields.pop("result"))
    if "sources_used" in fields:
        fields["sources_used"] = dumps(fields["sources_used"])
    fields["updated_at"] = now()
    with connect() as c:
        c.execute(f"UPDATE searches SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                  (*fields.values(), search_id))


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["input"] = json.loads(d.pop("query_json"))
    if "result_json" in d:
        d["result"] = loads(d.pop("result_json"))
    if "sources_used" in d:
        d["sources_used"] = loads(d["sources_used"])
    return d


def get(search_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
    return _row(r) if r else None


def list_for(user_id: int | None = None, case_id: str | None = None, limit: int = 100) -> list[dict]:
    where, args = [], []
    if user_id is not None:
        where.append("user_id = ?")
        args.append(user_id)
    if case_id is not None:
        where.append("case_id = ?")
        args.append(case_id)
    sql = f"SELECT {_LIST_COLS} FROM searches" + (" WHERE " + " AND ".join(where) if where else "")
    with connect() as c:
        rows = c.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, limit)).fetchall()
    return [_row(r) for r in rows]


def list_completed() -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM searches WHERE status = 'completed'").fetchall()
    return [_row(r) for r in rows]


def older_than(cutoff_iso: str) -> list[str]:
    with connect() as c:
        return [r[0] for r in c.execute("SELECT id FROM searches WHERE created_at < ?", (cutoff_iso,))]


def delete(search_id: str) -> bool:
    with connect() as c:
        cur = c.execute("DELETE FROM searches WHERE id = ?", (search_id,))
        c.execute("DELETE FROM feedback WHERE search_id = ?", (search_id,))
        c.execute("DELETE FROM evidence_chunks WHERE search_id = ?", (search_id,))
    return cur.rowcount > 0


def add_feedback(search_id: str, candidate_id: str, verdict: str, note: str | None, user_id: int):
    with connect() as c:
        c.execute("INSERT INTO feedback (search_id, candidate_id, verdict, note, user_id, created_at)"
                  " VALUES (?,?,?,?,?,?)", (search_id, candidate_id, verdict, note, user_id, now()))


def get_feedback(search_id: str) -> dict[str, str]:
    """Latest verdict per candidate."""
    with connect() as c:
        rows = c.execute("SELECT candidate_id, verdict FROM feedback WHERE search_id = ? ORDER BY id",
                         (search_id,)).fetchall()
    return {r["candidate_id"]: r["verdict"] for r in rows}


def count_since(since_iso: str) -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM searches WHERE created_at >= ?", (since_iso,)).fetchone()[0]


def fail_unfinished(reason: str):
    with connect() as c:
        c.execute("UPDATE searches SET status = 'failed', stage = 'Failed', error = ?, updated_at = ?"
                  " WHERE status IN ('queued', 'running')", (reason, now()))
