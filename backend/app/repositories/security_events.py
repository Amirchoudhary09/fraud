from ..core.database import ago, connect, new_id, now


def raise_event(type_: str, severity: str, detail: str, user_id: int | None = None,
                dedupe_key: str | None = None, dedupe_minutes: int = 30) -> str | None:
    """Creates an alert unless an identical open one was raised in the last dedupe_minutes."""
    with connect() as c:
        if dedupe_key and c.execute("SELECT 1 FROM security_events WHERE dedupe_key = ? AND ts >= ? LIMIT 1",
                                    (dedupe_key, ago(minutes=dedupe_minutes))).fetchone():
            return None
        sid = new_id("SEC")
        c.execute("INSERT INTO security_events (id, ts, severity, type, user_id, detail, status, dedupe_key)"
                  " VALUES (?,?,?,?,?,?,?,?)", (sid, now(), severity, type_, user_id, detail[:1000], "open", dedupe_key))
    return sid


def list_recent(status: str | None = None, limit: int = 200) -> list[dict]:
    sql = "SELECT s.*, u.email FROM security_events s LEFT JOIN users u ON u.id = s.user_id"
    args: tuple = ()
    if status:
        sql += " WHERE s.status = ?"
        args = (status,)
    with connect() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY s.ts DESC LIMIT ?", (*args, limit)).fetchall()]


def set_status(event_id: str, status: str, handled_by: int) -> bool:
    with connect() as c:
        cur = c.execute("UPDATE security_events SET status = ?, handled_by = ?, handled_at = ? WHERE id = ?",
                        (status, handled_by, now(), event_id))
    return cur.rowcount > 0


def count_open() -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM security_events WHERE status = 'open'").fetchone()[0]
