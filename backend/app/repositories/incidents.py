from ..core.database import connect, new_id, now


def create(case_id: str, reported_by: int, incident_type: str, severity: str, description: str | None,
           target_entity_id: str | None, source_platform: str | None, source_url: str | None,
           content_id: str | None, author_handle: str | None) -> str:
    iid, ts = new_id("INC"), now()
    with connect() as c:
        c.execute("INSERT INTO incidents (id, case_id, reported_by, target_entity_id, incident_type, source_platform,"
                  " source_url, content_id, author_handle, description, severity, status, created_at, updated_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (iid, case_id, reported_by, target_entity_id, incident_type, source_platform, source_url,
                   content_id, author_handle, description, severity, "open", ts, ts))
    return iid


def get(incident_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT i.*, e.display_name AS target_entity FROM incidents i"
                      " LEFT JOIN entities e ON e.id = i.target_entity_id WHERE i.id = ?", (incident_id,)).fetchone()
    return dict(r) if r else None


def list_for_case(case_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT i.*, e.display_name AS target_entity FROM incidents i"
                         " LEFT JOIN entities e ON e.id = i.target_entity_id WHERE i.case_id = ?"
                         " ORDER BY i.created_at", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def update(incident_id: str, **fields):
    fields = {k: v for k, v in fields.items() if v is not None and k in ("status", "severity", "description", "incident_type")}
    if not fields:
        return
    fields["updated_at"] = now()
    with connect() as c:
        c.execute(f"UPDATE incidents SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                  (*fields.values(), incident_id))


def count_since(since_iso: str) -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM incidents WHERE created_at >= ?", (since_iso,)).fetchone()[0]
