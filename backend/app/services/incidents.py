"""Incidents are separate from searches (spec section 16):

  SEARCH    "Amir searched Shahid"                      -> searches + USER ─SEARCHED→ ENTITY
  INCIDENT  "Amir reported an abusive comment by X"     -> incidents + USER ─CREATED_INCIDENT→ INCIDENT
  EVIDENCE  the actual public comment / screenshot / page -> evidence (hashed, encrypted)
  ANALYSIS  "potential harassment indicator"             -> analysis_results
A human reviewer decides what the incident means; the system never labels a person.
"""
from ..core.config import GEMINI_MODEL, MOCK_MODE
from ..providers import get_provider
from ..repositories import cases, entities
from ..repositories import evidence as evidence_repo
from ..repositories import incidents as repo
from . import audit
from . import comments as analyzer
from . import evidence as evidence_svc

_SEVERITY = {"none": 0, "low": 1, "medium": 2, "high": 3}


def analyze_evidence(case_id: str, incident_id: str | None, evidence_id: str, text: str) -> dict:
    model = "rules" if MOCK_MODE else f"rules+{GEMINI_MODEL}"
    aid = evidence_repo.start_analysis(case_id, incident_id, evidence_id, "CONTENT_INDICATORS", model)
    audit.record("ANALYSIS_STARTED", target_type="ANALYSIS", target_id=aid, case_id=case_id,
                 detail={"evidence_id": evidence_id})
    try:
        result = analyzer.analyze(text, get_provider())
    except Exception as e:
        evidence_repo.finish_analysis(aid, {"error": str(e)[:300]}, "failed")
        audit.record("ANALYSIS_COMPLETED", target_type="ANALYSIS", target_id=aid, case_id=case_id, result="FAILED")
        raise
    evidence_repo.finish_analysis(aid, result)
    audit.record("ANALYSIS_COMPLETED", target_type="ANALYSIS", target_id=aid, case_id=case_id,
                 detail={"severity": result["severity"], "suggested": result["suggested_incident_type"]})
    if incident_id:
        inc = repo.get(incident_id)
        if inc and _SEVERITY[result["severity"]] > _SEVERITY[inc["severity"]]:
            repo.update(incident_id, severity=result["severity"])
    return {"id": aid, **result}


def create_incident(case: dict, user: dict, data: dict) -> dict:
    handle, platform = analyzer.public_handle(data.get("author_handle"), data.get("source_url"))
    platform = data.get("source_platform") or platform
    if data.get("target_name"):
        target = entities.get_or_create("PERSON", data["target_name"])
    elif handle:
        target = entities.get_or_create("HANDLE", handle)
    else:
        target = None

    iid = repo.create(case["id"], user["id"], data.get("incident_type") or "OTHER", "none", data.get("description"),
                      target, platform, data.get("source_url"), data.get("content_id"), handle)
    entities.relate("USER", user["id"], "CREATED_INCIDENT", "INCIDENT", iid, case_id=case["id"], incident_id=iid)
    if target:
        entities.relate("INCIDENT", iid, "TARGETS", "ENTITY", target, case_id=case["id"], incident_id=iid)
        if not case.get("target_entity_id"):
            cases.update(case["id"], target_entity_id=target)
    audit.record("INCIDENT_CREATED", target_type="INCIDENT", target_id=iid, case_id=case["id"],
                 detail={"type": data.get("incident_type") or "OTHER", "target_entity_id": target})

    analysis = None
    if data.get("comment_text"):
        ev = evidence_svc.capture_text(case["id"], iid, data["comment_text"], user, "PUBLIC_COMMENT",
                                       data.get("source_url"),
                                       {"platform": platform, "author_handle": handle,
                                        "published_at": data.get("posted_at"), "content_id": data.get("content_id")})
        analysis = analyze_evidence(case["id"], iid, ev["id"], data["comment_text"])
        if not data.get("incident_type"):
            repo.update(iid, incident_type=analysis["suggested_incident_type"])
    return {**repo.get(iid), "analysis": analysis}

