from ..core.database import connect, new_id, now


def record(kind: str, fmt: str, content_hash: str, generated_by: int, case_id: str | None = None,
           search_id: str | None = None) -> str:
    rid = new_id("RPT")
    with connect() as c:
        c.execute("INSERT INTO reports (id, case_id, search_id, kind, format, content_hash, generated_by, generated_at)"
                  " VALUES (?,?,?,?,?,?,?,?)", (rid, case_id, search_id, kind, fmt, content_hash, generated_by, now()))
    return rid


def list_for_case(case_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT r.*, u.email AS generated_by_email FROM reports r LEFT JOIN users u"
                         " ON u.id = r.generated_by WHERE r.case_id = ? ORDER BY r.generated_at", (case_id,)).fetchall()
    return [dict(r) for r in rows]
