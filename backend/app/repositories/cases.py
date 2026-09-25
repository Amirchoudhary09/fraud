from ..core.database import connect, new_id, now


# --- cases -----------------------------------------------------------------------------

def create(title: str, description: str | None, purpose: str, created_by: int,
           target_entity_id: str | None = None) -> str:
    case_id, ts = new_id("CASE"), now()
    with connect() as c:
        c.execute("INSERT INTO cases (id, title, description, purpose, status, target_entity_id, created_by,"
                  " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (case_id, title, description, purpose, "open", target_entity_id, created_by, ts, ts))
        c.execute("INSERT INTO case_members (case_id, user_id, access, via, granted_by, granted_at)"
                  " VALUES (?,?,?,?,?,?)", (case_id, created_by, "owner", "owner", created_by, ts))
    return case_id


def get(case_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT c.*, u.email AS created_by_email, e.display_name AS target_entity"
                      " FROM cases c LEFT JOIN users u ON u.id = c.created_by"
                      " LEFT JOIN entities e ON e.id = c.target_entity_id WHERE c.id = ?", (case_id,)).fetchone()
    return dict(r) if r else None


_COUNTS = """(SELECT COUNT(*) FROM incidents i WHERE i.case_id = c.id) AS incident_count,
             (SELECT COUNT(*) FROM evidence v WHERE v.case_id = c.id) AS evidence_count,
             (SELECT COUNT(*) FROM searches s WHERE s.case_id = c.id) AS search_count,
             (SELECT COUNT(*) FROM reports r WHERE r.case_id = c.id) AS report_count"""


def list_visible(user_id: int | None, limit: int = 200) -> list[dict]:
    """Cases the user is an active member of; user_id=None lists all (case.view_all)."""
    sql = f"SELECT c.*, e.display_name AS target_entity, {_COUNTS} FROM cases c" \
          " LEFT JOIN entities e ON e.id = c.target_entity_id"
    args: tuple = ()
    if user_id is not None:
        sql += (" WHERE c.id IN (SELECT case_id FROM case_members WHERE user_id = ? AND revoked_at IS NULL"
                " AND (expires_at IS NULL OR expires_at > ?))")
        args = (user_id, now())
    with connect() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY c.created_at DESC LIMIT ?", (*args, limit)).fetchall()]


def counts(case_id: str) -> dict:
    with connect() as c:
        r = c.execute(f"SELECT {_COUNTS} FROM cases c WHERE c.id = ?", (case_id,)).fetchone()
    return dict(r) if r else {}


def update(case_id: str, **fields):
    fields = {k: v for k, v in fields.items() if v is not None}
    fields["updated_at"] = now()
    with connect() as c:
        c.execute(f"UPDATE cases SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                  (*fields.values(), case_id))


def delete(case_id: str) -> tuple[bool, list[str], list[str]]:
    """Deletes the case and everything in it. Returns (deleted, search ids, evidence file paths)."""
    with connect() as c:
        search_ids = [r[0] for r in c.execute("SELECT id FROM searches WHERE case_id = ?", (case_id,))]
        paths = [r[0] for r in c.execute("SELECT storage_path FROM evidence WHERE case_id = ? AND storage_path"
                                         " IS NOT NULL", (case_id,))]
        cur = c.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        for table in ("case_members", "break_glass_requests", "incidents", "evidence", "analysis_results",
                      "reports", "relationships"):
            c.execute(f"DELETE FROM {table} WHERE case_id = ?", (case_id,))
    return cur.rowcount > 0, search_ids, paths


def count_active() -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM cases WHERE status != 'closed'").fetchone()[0]


def older_than(cutoff_iso: str) -> list[str]:
    with connect() as c:
        return [r[0] for r in c.execute("SELECT id FROM cases WHERE created_at < ?", (cutoff_iso,))]


# --- case-level access -----------------------------------------------------------------

def membership(case_id: str, user_id: int) -> dict | None:
    """Strongest active membership of the user on the case."""
    with connect() as c:
        rows = c.execute("SELECT * FROM case_members WHERE case_id = ? AND user_id = ? AND revoked_at IS NULL"
                         " AND (expires_at IS NULL OR expires_at > ?)", (case_id, user_id, now())).fetchall()
    order = {"owner": 3, "editor": 2, "viewer": 1}
    return dict(max(rows, key=lambda r: order[r["access"]])) if rows else None


def members(case_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT m.*, u.email FROM case_members m JOIN users u ON u.id = m.user_id"
                         " WHERE m.case_id = ? ORDER BY m.granted_at", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def grant(case_id: str, user_id: int, access: str, granted_by: int, via: str = "grant",
          expires_at: str | None = None) -> int:
    with connect() as c:
        cur = c.execute("INSERT INTO case_members (case_id, user_id, access, via, granted_by, granted_at, expires_at)"
                        " VALUES (?,?,?,?,?,?,?)", (case_id, user_id, access, via, granted_by, now(), expires_at))
    return cur.lastrowid


def revoke(case_id: str, member_id: int) -> bool:
    with connect() as c:
        cur = c.execute("UPDATE case_members SET revoked_at = ? WHERE id = ? AND case_id = ? AND via != 'owner'"
                        " AND revoked_at IS NULL", (now(), member_id, case_id))
    return cur.rowcount > 0


# --- break-glass -----------------------------------------------------------------------

def create_break_glass(case_id: str, user_id: int, reason: str) -> str:
    bid = new_id("BG")
    with connect() as c:
        c.execute("INSERT INTO break_glass_requests (id, case_id, user_id, reason, status, created_at)"
                  " VALUES (?,?,?,?,?,?)", (bid, case_id, user_id, reason, "pending", now()))
    return bid


def get_break_glass(bid: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT b.*, u.email FROM break_glass_requests b JOIN users u ON u.id = b.user_id"
                      " WHERE b.id = ?", (bid,)).fetchone()
    return dict(r) if r else None


def list_break_glass(status: str | None = None) -> list[dict]:
    sql = ("SELECT b.*, u.email, c.title AS case_title FROM break_glass_requests b JOIN users u ON u.id = b.user_id"
           " LEFT JOIN cases c ON c.id = b.case_id")
    args: tuple = ()
    if status:
        sql += " WHERE b.status = ?"
        args = (status,)
    with connect() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY b.created_at DESC LIMIT 200", args).fetchall()]


def decide_break_glass(bid: str, status: str, decided_by: int, expires_at: str | None):
    with connect() as c:
        c.execute("UPDATE break_glass_requests SET status = ?, decided_by = ?, decided_at = ?, expires_at = ?"
                  " WHERE id = ?", (status, decided_by, now(), expires_at, bid))
