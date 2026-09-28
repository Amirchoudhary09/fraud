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
