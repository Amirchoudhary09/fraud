"""Entities (people/handles being searched or reported) and explicit relationships:
USER ─SEARCHED→ ENTITY, USER ─CREATED_INCIDENT→ INCIDENT, INCIDENT ─TARGETS→ ENTITY,
INCIDENT ─CONTAINS→ EVIDENCE."""
import sqlite3

from ..core.database import connect, new_id, now


def normalized_key(entity_type: str, name: str) -> str:
    return f"{entity_type}:{' '.join(name.lower().lstrip('@').split())}"


def get_or_create(entity_type: str, display_name: str) -> str:
    key = normalized_key(entity_type, display_name)
    with connect() as c:
        r = c.execute("SELECT id FROM entities WHERE normalized_key = ?", (key,)).fetchone()
        if r:
            return r[0]
        eid = new_id("ENT")
        try:
            c.execute("INSERT INTO entities (id, entity_type, display_name, normalized_key, created_at)"
                      " VALUES (?,?,?,?,?)", (eid, entity_type, display_name, key, now()))
        except sqlite3.IntegrityError:  # created concurrently
            return c.execute("SELECT id FROM entities WHERE normalized_key = ?", (key,)).fetchone()[0]
    return eid


def get(entity_id: str) -> dict | None:
    with connect() as c:
        r = c.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return dict(r) if r else None


def relate(subject_type: str, subject_id, relationship_type: str, object_type: str, object_id: str,
           search_id: str | None = None, case_id: str | None = None, incident_id: str | None = None) -> str:
    rid = new_id("REL")
    with connect() as c:
        c.execute("INSERT INTO relationships (id, subject_type, subject_id, relationship_type, object_type, object_id,"
                  " search_id, case_id, incident_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (rid, subject_type, str(subject_id), relationship_type, object_type, object_id,
                   search_id, case_id, incident_id, now()))
    return rid


def relationships(subject_type: str | None = None, subject_id=None, object_id: str | None = None,
                  case_id: str | None = None, limit: int = 500) -> list[dict]:
    where, args = [], []
    for col, val in (("subject_type", subject_type), ("subject_id", None if subject_id is None else str(subject_id)),
                     ("object_id", object_id), ("case_id", case_id)):
        if val is not None:
            where.append(f"r.{col} = ?")
            args.append(val)
    sql = ("SELECT r.*, e.display_name AS object_label FROM relationships r"
           " LEFT JOIN entities e ON e.id = r.object_id" + (" WHERE " + " AND ".join(where) if where else ""))
    with connect() as c:
        return [dict(r) for r in c.execute(sql + " ORDER BY r.created_at DESC LIMIT ?", (*args, limit)).fetchall()]
