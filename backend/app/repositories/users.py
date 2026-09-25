import uuid

from ..core.database import connect, in_future, now

_PUBLIC = "id, email, role, status, mfa_enabled, created_at, last_login_at"


def count(active_only: bool = False) -> int:
    sql = "SELECT COUNT(*) FROM users" + (" WHERE status = 'active'" if active_only else "")
    with connect() as c:
        return c.execute(sql).fetchone()[0]


def create(email: str, password_hash: str, role: str) -> dict:
    with connect() as c:
        cur = c.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES (?,?,?,?)",
                        (email.lower(), password_hash, role, now()))
    return get(cur.lastrowid)


def get(user_id: int) -> dict | None:
    with connect() as c:
        r = c.execute(f"SELECT {_PUBLIC} FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(r) if r else None


def get_private(user_id: int) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(r) if r else None


def get_by_email_private(email: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
    return dict(r) if r else None


def list_all() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(f"SELECT {_PUBLIC} FROM users ORDER BY id").fetchall()]


def update(user_id: int, **fields) -> dict | None:
    allowed = {"role", "status", "mfa_secret_enc", "mfa_enabled", "last_login_at", "password_hash"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if fields:
        with connect() as c:
            c.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
                      (*fields.values(), user_id))
    return get(user_id)


def clear_mfa(user_id: int):
    with connect() as c:
        c.execute("UPDATE users SET mfa_secret_enc = NULL, mfa_enabled = 0 WHERE id = ?", (user_id,))


# --- refresh tokens (rotating; reuse of a rotated token revokes the whole session family) ---

def store_refresh(user_id: int, token_hash: str, days: int, family_id: str | None = None) -> int:
    with connect() as c:
        cur = c.execute("INSERT INTO refresh_tokens (user_id, token_hash, family_id, created_at, expires_at)"
                        " VALUES (?,?,?,?,?)",
                        (user_id, token_hash, family_id or uuid.uuid4().hex, now(), in_future(days=days)))
    return cur.lastrowid


def get_refresh(token_hash: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
    return dict(r) if r else None


def rotate_refresh(old_id: int, new_id: int):
    with connect() as c:
        c.execute("UPDATE refresh_tokens SET revoked_at = ?, replaced_by = ? WHERE id = ?", (now(), new_id, old_id))


def revoke_family(family_id: str):
    with connect() as c:
        c.execute("UPDATE refresh_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE family_id = ?",
                  (now(), family_id))


def revoke_all_for_user(user_id: int):
    with connect() as c:
        c.execute("UPDATE refresh_tokens SET revoked_at = COALESCE(revoked_at, ?) WHERE user_id = ?",
                  (now(), user_id))
