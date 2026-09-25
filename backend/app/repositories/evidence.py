"""Evidence objects (own IDs, separate from incidents) and AI analysis results."""
from ..core.database import connect, dumps, loads, new_id, now

_META = ("id, case_id, incident_id, type, source_url, capture_method, captured_by, captured_at, content_hash,"
         " mime_type, size, metadata_json, storage_path IS NOT NULL AS has_file")


def _row(r) -> dict:
    d = dict(r)
    d["metadata"] = loads(d.pop("metadata_json", None)) or {}
    return d


def create(case_id: str, incident_id: str | None, type_: str, capture_method: str, captured_by: int,
           content_hash: str, content_enc: str | None = None, storage_path: str | None = None,
           source_url: str | None = None, mime_type: str | None = None, size: int | None = None,
           metadata: dict | None = None) -> str:
    eid = new_id("EVD")
    with connect() as c:
        c.execute("INSERT INTO evidence (id, case_id, incident_id, type, source_url, capture_method, captured_by,"
                  " captured_at, content_hash, content_enc, storage_path, mime_type, size, metadata_json)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (eid, case_id, incident_id, type_, source_url, capture_method, captured_by, now(), content_hash,
                   content_enc, storage_path, mime_type, size, dumps(metadata or {})))
    return eid


def get(evidence_id: str) -> dict | None:
    with connect() as c:
        r = c.execute(f"SELECT {_META} FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    return _row(r) if r else None


def get_private(evidence_id: str) -> dict | None:
    """Includes encrypted content and storage path; for services only, never returned by the API."""
    with connect() as c:
        r = c.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
    return _row(r) if r else None


def list_for_case(case_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(f"SELECT {_META} FROM evidence WHERE case_id = ? ORDER BY captured_at", (case_id,)).fetchall()
    return [_row(r) for r in rows]


def path_in_use(path: str) -> bool:
    with connect() as c:
        return c.execute("SELECT 1 FROM evidence WHERE storage_path = ? LIMIT 1", (path,)).fetchone() is not None


def count_since(since_iso: str) -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM evidence WHERE captured_at >= ?", (since_iso,)).fetchone()[0]


# --- analysis results ------------------------------------------------------------------

def start_analysis(case_id: str, incident_id: str | None, evidence_id: str, analysis_type: str, model: str) -> str:
    aid = new_id("ANL")
    with connect() as c:
        c.execute("INSERT INTO analysis_results (id, case_id, incident_id, evidence_id, analysis_type, model, status,"
                  " started_at) VALUES (?,?,?,?,?,?,?,?)",
                  (aid, case_id, incident_id, evidence_id, analysis_type, model, "running", now()))
    return aid


def finish_analysis(analysis_id: str, result: dict | None, status: str = "completed"):
    with connect() as c:
        c.execute("UPDATE analysis_results SET status = ?, result_json = ?, completed_at = ? WHERE id = ?",
                  (status, dumps(result), now(), analysis_id))


def analyses_for_case(case_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM analysis_results WHERE case_id = ? ORDER BY started_at", (case_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["result"] = loads(d.pop("result_json"))
        out.append(d)
    return out
