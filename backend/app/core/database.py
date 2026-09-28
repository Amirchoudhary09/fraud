"""Application database (SQLite) and schema. The audit log is NOT here: see audit_store.py.

Data model (spec section 17):

USER ─┬─ SEARCH ── candidates (result_json) ── feedback
      │     └── SEARCHED ──> ENTITY            (relationships)
      ├─ CASE ── case_members / break_glass_requests
      │    ├── INCIDENT ──TARGETS──> ENTITY
      │    │      ├── EVIDENCE (hashed, encrypted)
      │    │      └── ANALYSIS_RESULT
      │    └── REPORT (hashed)
      └─ SECURITY_EVENTS (monitoring alerts)

Repositories in app/repositories are the only code that runs SQL. SQLite by default;
set DATABASE_URL=postgresql://... to use PostgreSQL (required for more than one API replica).
"""
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',     -- active | disabled
    mfa_secret_enc TEXT,
    mfa_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    family_id TEXT NOT NULL,                    -- one login session; reuse revokes the family
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    replaced_by INTEGER
);
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,                       -- open | under_review | closed
    target_entity_id TEXT,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    access TEXT NOT NULL,                       -- owner | editor | viewer
    via TEXT NOT NULL,                          -- owner | grant | break_glass
    granted_by INTEGER,
    granted_at TEXT NOT NULL,
    expires_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_members ON case_members(case_id, user_id);
CREATE TABLE IF NOT EXISTS break_glass_requests (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,                       -- pending | approved | denied
    created_at TEXT NOT NULL,
    decided_by INTEGER,
    decided_at TEXT,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS searches (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    case_id TEXT,
    incident_id TEXT,
    entity_id TEXT,
    search_type TEXT NOT NULL,                  -- PUBLIC_IDENTITY | INCIDENT_AUTHOR
    query_json TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    purpose TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,                       -- queued | running | completed | failed
    stage TEXT NOT NULL,
    sources_used TEXT,
    candidate_count INTEGER,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_searches_user ON searches(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_searches_case ON searches(case_id);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    note TEXT,
    user_id INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,                  -- PERSON | HANDLE
    display_name TEXT NOT NULL,
    normalized_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,                 -- USER | INCIDENT | SEARCH
    subject_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,            -- SEARCHED | CREATED_INCIDENT | TARGETS | CONTAINS
    object_type TEXT NOT NULL,                  -- ENTITY | INCIDENT | EVIDENCE
    object_id TEXT NOT NULL,
    search_id TEXT,
    case_id TEXT,
    incident_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_subject ON relationships(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_rel_object ON relationships(object_type, object_id);
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    reported_by INTEGER NOT NULL,
    target_entity_id TEXT,
    incident_type TEXT NOT NULL,
    source_platform TEXT,
    source_url TEXT,
    content_id TEXT,
    author_handle TEXT,
    description TEXT,
    severity TEXT NOT NULL,                     -- none | low | medium | high
    status TEXT NOT NULL,                       -- open | under_review | resolved | dismissed
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    incident_id TEXT,
    type TEXT NOT NULL,                         -- PUBLIC_COMMENT | SCREENSHOT | WEB_PAGE | DOCUMENT
    source_url TEXT,
    capture_method TEXT NOT NULL,               -- USER_SUBMITTED_TEXT | FILE_UPLOAD | SAFE_FETCH
    captured_by INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,                 -- SHA-256 of the canonical plaintext
    content_enc TEXT,                           -- encrypted text content
    storage_path TEXT,                          -- encrypted file on disk
    mime_type TEXT,
    size INTEGER,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id);
CREATE TABLE IF NOT EXISTS analysis_results (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    incident_id TEXT,
    evidence_id TEXT NOT NULL,
    analysis_type TEXT NOT NULL,                -- CONTENT_INDICATORS
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    case_id TEXT,
    search_id TEXT,
    kind TEXT NOT NULL,                         -- CASE | SEARCH
    format TEXT NOT NULL,                       -- html | pdf
    content_hash TEXT NOT NULL,
    generated_by INTEGER NOT NULL,
    generated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id TEXT NOT NULL,
    candidate_id TEXT,
    text TEXT NOT NULL,
    source_url TEXT,
    source_title TEXT,
    vector_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_search ON evidence_chunks(search_id);
CREATE TABLE IF NOT EXISTS security_events (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    severity TEXT NOT NULL,                     -- low | medium | high | critical
    type TEXT NOT NULL,
    user_id INTEGER,
    detail TEXT,
    status TEXT NOT NULL,                       -- open | acknowledged | resolved
    handled_by INTEGER,
    handled_at TEXT,
    dedupe_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_sec_dedupe ON security_events(dedupe_key, ts);
CREATE TABLE IF NOT EXISTS kv (                 -- small operational state, e.g. export cursors
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def in_future(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


def ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# --- dialects ------------------------------------------------------------------------------
# Repositories write portable SQL with "?" placeholders and "RETURNING". On PostgreSQL the
# placeholders are translated and rows support both row[0] and row["col"], like sqlite3.Row.

class Row(tuple):
    """Tuple row that also supports row["col"], .keys() and dict(row)."""
    _names: tuple = ()

    def __new__(cls, names, values):
        r = super().__new__(cls, values)
        r._names = names
        return r

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._names.index(key))
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._names)


def _pg_row_factory(cursor):
    names = tuple(d.name for d in cursor.description or ())
    return lambda values: Row(names, values)


class _PgConn:
    """Minimal sqlite3-style facade over a psycopg connection."""

    def __init__(self, conn):
        self._c = conn

    def execute(self, sql: str, params=()):
        return self._c.execute(sql.replace("?", "%s"), params)

    def executemany(self, sql: str, seq):
        cur = self._c.cursor()
        cur.executemany(sql.replace("?", "%s"), seq)
        return cur


def is_postgres(target) -> bool:
    return isinstance(target, str) and target.startswith(("postgres://", "postgresql://"))


def integrity_errors() -> tuple:
    errs: tuple = (sqlite3.IntegrityError,)
    try:
        import psycopg
        errs += (psycopg.errors.IntegrityError,)
    except ImportError:
        pass
    return errs


@contextmanager
def open_db(target, lock=None):
    """Connection to a SQLite file path or a PostgreSQL URL; commits on success."""
    if is_postgres(target):
        import psycopg
        conn = psycopg.connect(target, row_factory=_pg_row_factory)
        try:
            yield _PgConn(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (lock or threading.Lock()):
        conn = sqlite3.connect(path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def app_target():
    return config.DATABASE_URL or config.DB_PATH


@contextmanager
def connect():
    with open_db(app_target(), _lock) as c:
        yield c


def pg_schema(sqlite_schema: str) -> list[str]:
    ddl = re.sub(r"--[^\n]*", "", sqlite_schema)  # comments may contain ';'
    ddl = ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
    return [s.strip() for s in ddl.split(";") if s.strip()]


def init():
    with connect() as c:
        if is_postgres(app_target()):
            for stmt in pg_schema(SCHEMA):
                c.execute(stmt)
        else:
            c.executescript(SCHEMA)


def loads(value: str | None):
    return json.loads(value) if value else None


def dumps(value) -> str | None:
    return json.dumps(value) if value is not None else None
