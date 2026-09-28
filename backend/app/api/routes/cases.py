import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from ...core import permissions
from ...core.database import in_future
from ...reports import builder, html, pdf
from ...repositories import cases, incidents, reports, searches, users
from ...repositories import evidence as evidence_repo
from ...schemas.case import (BreakGlassCreate, CaseCreate, CaseUpdate, EvidenceText, EvidenceUrl, IncidentCreate,
                             IncidentInvestigate, IncidentUpdate, MemberGrant)
from ...schemas.identity import IdentityInput
from ...services import audit, intake, retention, safe_fetch, timeline
from ...services import evidence as evidence_svc
from ...services import incidents as incident_svc
from ..access import case_access
from ..deps import current_user, deny, need

router = APIRouter(prefix="/api/cases", tags=["cases"])


# --- cases -----------------------------------------------------------------------------

@router.post("", status_code=201)
def create_case(body: CaseCreate, user: dict = Depends(need("case.create"))):
    case_id = cases.create(body.title, body.description, body.purpose, user["id"])
    audit.record("CASE_CREATED", target_type="CASE", target_id=case_id, case_id=case_id,
                 detail={"purpose": body.purpose})
    return cases.get(case_id)


@router.get("")
def list_cases(user: dict = Depends(current_user)):
    view_all = permissions.has(user["role"], "case.view_all")
    return cases.list_visible(None if view_all else user["id"])


@router.get("/{case_id}")
def get_case(case_id: str, user: dict = Depends(current_user)):
    case = case_access(user, case_id)
    audit.record("CASE_VIEWED", target_type="CASE", target_id=case_id, case_id=case_id)
    m = cases.membership(case_id, user["id"])
    return {
        **case, **cases.counts(case_id),
        "my_access": m["access"] if m else ("admin" if permissions.has(user["role"], "case.view_all") else None),
        "incidents": incidents.list_for_case(case_id),
        "evidence": evidence_repo.list_for_case(case_id),
        "analyses": evidence_repo.analyses_for_case(case_id),
        "searches": searches.list_for(case_id=case_id),
        "reports": reports.list_for_case(case_id),
        "members": cases.members(case_id),
    }


@router.patch("/{case_id}")
def update_case(case_id: str, body: CaseUpdate, user: dict = Depends(current_user)):
    case_access(user, case_id, "editor")
    cases.update(case_id, **body.model_dump(exclude_none=True))
    audit.record("CASE_UPDATED", target_type="CASE", target_id=case_id, case_id=case_id,
                 detail=body.model_dump(exclude_none=True, exclude={"description"}))
    return cases.get(case_id)


@router.delete("/{case_id}")
def delete_case(case_id: str, _: dict = Depends(need("data.delete"))):
    if not retention.delete_case(case_id):
        raise HTTPException(404, "Case not found")
    audit.record("CASE_DELETED", target_type="CASE", target_id=case_id, case_id=case_id)
    return {"deleted": case_id}


# --- case-level access -----------------------------------------------------------------

@router.post("/{case_id}/members", status_code=201)
def grant_access(case_id: str, body: MemberGrant, user: dict = Depends(need("case.share"))):
    case_access(user, case_id, "owner")
    target = users.get_by_email_private(body.email)
    if not target or target["status"] != "active":
        raise HTTPException(404, "No active user with that email")
    expires = in_future(hours=body.expires_hours) if body.expires_hours else None
    mid = cases.grant(case_id, target["id"], body.access, user["id"], "grant", expires)
    audit.record("CASE_ACCESS_GRANTED", target_type="USER", target_id=str(target["id"]), case_id=case_id,
                 detail={"access": body.access, "expires_at": expires, "member_id": mid})
    return cases.members(case_id)


@router.delete("/{case_id}/members/{member_id}")
def revoke_access(case_id: str, member_id: int, user: dict = Depends(need("case.share"))):
    case_access(user, case_id, "owner")
    if not cases.revoke(case_id, member_id):
        raise HTTPException(404, "Active grant not found (owners cannot be removed)")
    audit.record("CASE_ACCESS_REVOKED", target_type="CASE_MEMBER", target_id=str(member_id), case_id=case_id)
    return cases.members(case_id)


@router.post("/{case_id}/break-glass", status_code=201)
def request_break_glass(case_id: str, body: BreakGlassCreate, user: dict = Depends(current_user)):
    """Emergency access request: needs a reason and approval by a security admin; always alerts."""
    if not cases.get(case_id):
        raise HTTPException(404, "Case not found")
    bid = cases.create_break_glass(case_id, user["id"], body.reason)
    audit.record("BREAK_GLASS_REQUESTED", target_type="BREAK_GLASS", target_id=bid, case_id=case_id,
                 detail={"reason": body.reason[:300]})
    return cases.get_break_glass(bid)


@router.get("/{case_id}/timeline")
def case_timeline(case_id: str, user: dict = Depends(current_user)):
    case_access(user, case_id)
    return timeline.case_timeline(case_id)


@router.get("/{case_id}/access-history")
def access_history(case_id: str, user: dict = Depends(current_user)):
    if permissions.has(user["role"], "audit.view"):
        if not cases.get(case_id):
            raise HTTPException(404, "Case not found")
    elif permissions.has(user["role"], "audit.view_case"):
        case_access(user, case_id, "owner")
    else:
        deny(user, "Viewing a case's access history needs audit permissions", "CASE", case_id, case_id)
    audit.record("AUDIT_VIEWED", target_type="CASE", target_id=case_id, case_id=case_id, detail="access-history")
    return timeline.access_history(case_id)


# --- incidents -------------------------------------------------------------------------

def _incident(case_id: str, incident_id: str) -> dict:
    inc = incidents.get(incident_id)
    if not inc or inc["case_id"] != case_id:
        raise HTTPException(404, "Incident not found")
    return inc


@router.post("/{case_id}/incidents", status_code=201)
def create_incident(case_id: str, body: IncidentCreate, user: dict = Depends(need("incident.create"))):
    case = case_access(user, case_id, "editor")
    return incident_svc.create_incident(case, user, body.model_dump())


@router.patch("/{case_id}/incidents/{incident_id}")
def update_incident(case_id: str, incident_id: str, body: IncidentUpdate, user: dict = Depends(need("incident.create"))):
    case_access(user, case_id, "editor")
    _incident(case_id, incident_id)
    incidents.update(incident_id, **body.model_dump(exclude_none=True))
    audit.record("INCIDENT_UPDATED", target_type="INCIDENT", target_id=incident_id, case_id=case_id,
                 detail=body.model_dump(exclude_none=True, exclude={"description"}))
    return incidents.get(incident_id)


@router.post("/{case_id}/incidents/{incident_id}/investigate", status_code=202)
def investigate_author(case_id: str, incident_id: str, hints: IncidentInvestigate,
                       user: dict = Depends(need("search.create"))):
    """Incident -> public author handle -> public web search -> candidates -> identity resolution."""
    case = case_access(user, case_id, "editor")
    inc = _incident(case_id, incident_id)
    handle = inc.get("author_handle")
    if not handle:
        raise HTTPException(400, "This incident has no public author handle or profile URL to start from.")
    identity = IdentityInput(name=hints.name or handle, username=handle, company=hints.company,
                             college=hints.college, location=hints.location)
    sid = intake.start_search(identity, case["purpose"], user, case_id=case_id, incident_id=incident_id,
                              search_type="INCIDENT_AUTHOR")
    return {"id": sid}


# --- evidence --------------------------------------------------------------------------

def _check_incident(case_id: str, incident_id: str | None):
    if incident_id:
        _incident(case_id, incident_id)


@router.post("/{case_id}/evidence/text", status_code=201)
def add_text_evidence(case_id: str, body: EvidenceText, user: dict = Depends(need("evidence.capture"))):
    case_access(user, case_id, "editor")
    _check_incident(case_id, body.incident_id)
    ev = evidence_svc.capture_text(case_id, body.incident_id, body.text, user, body.type, body.source_url)
    analysis = incident_svc.analyze_evidence(case_id, body.incident_id, ev["id"], body.text) \
        if body.type == "PUBLIC_COMMENT" else None
    return {**ev, "analysis": analysis}


@router.post("/{case_id}/evidence/file", status_code=201)
async def add_file_evidence(case_id: str, file: UploadFile = File(...), incident_id: str | None = Form(None),
                            source_url: str | None = Form(None), user: dict = Depends(need("evidence.capture"))):
    case_access(user, case_id, "editor")
    _check_incident(case_id, incident_id)
    data = await file.read()
    name = (file.filename or "upload").replace("/", "_").replace("\\", "_")[:200]
    etype = "SCREENSHOT" if (file.content_type or "").startswith("image/") else "DOCUMENT"
    try:
        return evidence_svc.capture_file(case_id, incident_id, data, file.content_type or "", name, user, etype,
                                         source_url)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{case_id}/evidence/url", status_code=201)
def add_url_evidence(case_id: str, body: EvidenceUrl, user: dict = Depends(need("evidence.capture"))):
    case_access(user, case_id, "editor")
    _check_incident(case_id, body.incident_id)
    try:
        return evidence_svc.capture_url(case_id, body.incident_id, body.url, user)
    except safe_fetch.FetchBlocked as e:
        audit.record("EVIDENCE_CAPTURE_BLOCKED", target_type="URL", case_id=case_id, result="DENIED", detail=str(e))
        raise HTTPException(400, f"URL not captured: {e}")
    except Exception as e:
        raise HTTPException(502, f"Could not fetch the page: {type(e).__name__}")


def _evidence(case_id: str, evidence_id: str) -> dict:
    ev = evidence_repo.get(evidence_id)
    if not ev or ev["case_id"] != case_id:
        raise HTTPException(404, "Evidence not found")
    return ev


@router.get("/{case_id}/evidence/{evidence_id}")
def view_evidence(case_id: str, evidence_id: str, user: dict = Depends(current_user)):
    case_access(user, case_id)
    ev = _evidence(case_id, evidence_id)
    audit.record("EVIDENCE_VIEWED", target_type="EVIDENCE", target_id=evidence_id, case_id=case_id)
    if not ev["has_file"]:
        _, data = evidence_svc.read(evidence_id)
        ev["text"] = data.decode()
    return ev


@router.get("/{case_id}/evidence/{evidence_id}/download")
def download_evidence(case_id: str, evidence_id: str, user: dict = Depends(need("evidence.export"))):
    case_access(user, case_id)
    ev = _evidence(case_id, evidence_id)
    _, data = evidence_svc.read(evidence_id)
    audit.record("EVIDENCE_DOWNLOADED", target_type="EVIDENCE", target_id=evidence_id, case_id=case_id,
                 detail={"sha256": ev["content_hash"]})
    name = ev["metadata"].get("filename") or f"{evidence_id}.txt"
    return Response(data, media_type=ev["mime_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "X-Evidence-SHA256": ev["content_hash"]})


@router.post("/{case_id}/evidence/{evidence_id}/verify")
def verify_evidence(case_id: str, evidence_id: str, user: dict = Depends(current_user)):
    case_access(user, case_id)
    _evidence(case_id, evidence_id)
    return evidence_svc.verify(evidence_id)


# --- reports ---------------------------------------------------------------------------

def _doc(case_id: str) -> dict:
    case = cases.get(case_id)
    srch = [searches.get(s["id"]) for s in searches.list_for(case_id=case_id)]
    fb = {s["id"]: searches.get_feedback(s["id"]) for s in srch}
    evs = evidence_repo.list_for_case(case_id)
    texts = {e["id"]: evidence_svc.read(e["id"])[1].decode() for e in evs if e["type"] == "PUBLIC_COMMENT"}
    return builder.case_report(case, incidents.list_for_case(case_id), evs, evidence_repo.analyses_for_case(case_id),
                               srch, fb, timeline.case_timeline(case_id), texts)


@router.get("/{case_id}/report", response_class=HTMLResponse)
def report_html(case_id: str, user: dict = Depends(need("report.view"))):
    case_access(user, case_id)
    body = html.render(_doc(case_id))
    rid = reports.record("CASE", "html", hashlib.sha256(body.encode()).hexdigest(), user["id"], case_id=case_id)
    audit.record("REPORT_GENERATED", target_type="REPORT", target_id=rid, case_id=case_id)
    return body


@router.get("/{case_id}/report.pdf")
def report_pdf(case_id: str, user: dict = Depends(need("evidence.export"))):
    case_access(user, case_id)
    data = pdf.render(_doc(case_id))
    rid = reports.record("CASE", "pdf", hashlib.sha256(data).hexdigest(), user["id"], case_id=case_id)
    audit.record("REPORT_EXPORTED", target_type="REPORT", target_id=rid, case_id=case_id, detail={"format": "pdf"})
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="case-report-{case_id}.pdf"'})
