import json

from ..core.database import connect, now


def get(key: str, default=None):
    with connect() as c:
        r = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def set(key: str, value):  # noqa: A001 - mirrors dict-style naming
    with connect() as c:
        c.execute("INSERT INTO kv (key, value, updated_at) VALUES (?,?,?)"
                  " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                  (key, json.dumps(value), now()))


def pop(key: str, default=None):
    """Atomically reads and deletes a key (single-use tokens such as OIDC state)."""
    with connect() as c:
        r = c.execute("DELETE FROM kv WHERE key = ? RETURNING value", (key,)).fetchone()
    return json.loads(r[0]) if r else default
