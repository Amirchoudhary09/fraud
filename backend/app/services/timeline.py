"""Case evidence timeline and access history, both derived from the tamper-evident audit log."""
from ..core import audit_store
from ..repositories import searches, users

LABELS = {
    "CASE_CREATED": "created the case",
    "CASE_UPDATED": "updated the case",
    "SEARCH_STARTED": "started a search",
    "CANDIDATE_CREATED": "candidate discovered",
    "SEARCH_COMPLETED": "search completed",
    "SEARCH_FAILED": "search failed",
    "INCIDENT_CREATED": "created an incident",
    "INCIDENT_UPDATED": "updated an incident",
    "EVIDENCE_CAPTURED": "captured evidence",
    "ANALYSIS_STARTED": "AI analysis started",
    "ANALYSIS_COMPLETED": "AI analysis completed",
    "EVIDENCE_INTEGRITY_VERIFIED": "verified evidence integrity",
    "EVIDENCE_INTEGRITY_FAILED": "evidence integrity check FAILED",
    "CANDIDATE_FEEDBACK": "reviewed a candidate",
    "REPORT_GENERATED": "generated a report",
    "REPORT_EXPORTED": "exported a report",
    "CASE_ACCESS_GRANTED": "granted case access",
    "CASE_ACCESS_REVOKED": "revoked case access",
    "BREAK_GLASS_REQUESTED": "requested break-glass access",
    "BREAK_GLASS_APPROVED": "break-glass access approved",
    "BREAK_GLASS_DENIED": "break-glass access denied",
}
ACCESS_TYPES = {"CASE_VIEWED", "ADMIN_CASE_ACCESS", "EVIDENCE_VIEWED", "EVIDENCE_DOWNLOADED", "REPORT_GENERATED",
                "REPORT_EXPORTED", "SEARCH_VIEWED", "CASE_ACCESS_GRANTED", "CASE_ACCESS_REVOKED",
                "BREAK_GLASS_APPROVED", "AUTHZ_DENIED"}


def _events(case_id: str) -> list[dict]:
    sids = [s["id"] for s in searches.list_for(case_id=case_id, limit=500)]
    events = audit_store.for_case(case_id, sids)
    emails = {u["id"]: u["email"] for u in users.list_all()}
    for e in events:
        e["actor_email"] = emails.get(e["actor_user_id"], "system" if e["actor_user_id"] is None else "?")
    return events


def case_timeline(case_id: str) -> list[dict]:
    return [{"ts": e["ts"], "event_type": e["event_type"], "actor": e["actor_email"],
             "text": f"{e['actor_email']} {LABELS[e['event_type']]}", "target_type": e["target_type"],
             "target_id": e["target_id"], "result": e["result"], "event_id": e["event_id"]}
            for e in _events(case_id) if e["event_type"] in LABELS]


def access_history(case_id: str) -> list[dict]:
    return [{"ts": e["ts"], "event_type": e["event_type"], "actor": e["actor_email"], "target_type": e["target_type"],
             "target_id": e["target_id"], "result": e["result"], "event_id": e["event_id"]}
            for e in _events(case_id) if e["event_type"] in ACCESS_TYPES]
