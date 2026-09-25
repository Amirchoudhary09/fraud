import hashlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response

from ...core import config, permissions, ratelimit
from ...providers import get_provider
from ...reports import builder, html, pdf
from ...repositories import reports, searches
from ...schemas.identity import FeedbackRequest, InvestigationRequest, Question
from ...services import audit, graph, intake, rag
from ..access import case_access, search_access
from ..deps import deny, need

router = APIRouter(prefix="/api/searches", tags=["searches"])


def _completed(user: dict, search_id: str) -> dict:
    s = search_access(user, search_id)
    if s["status"] != "completed":
        raise HTTPException(409, "Search is not complete yet")
    return s


@router.post("", status_code=202)
def create(req: InvestigationRequest, user: dict = Depends(need("search.create"))):
    if req.case_id:
        case_access(user, req.case_id, "editor")
    return {"id": intake.start_search(req.identity, req.purpose, user, case_id=req.case_id)}


@router.get("")
def list_searches(case_id: str | None = None, scope: str = "mine", user: dict = Depends(need("search.view_own"))):
    """scope=mine (default): my search history. case_id: searches in a case I can access.
    scope=all: everyone's (search.view_all only, audited)."""
    if case_id:
        case_access(user, case_id)
        return searches.list_for(case_id=case_id)
    if scope == "all":
        if not permissions.has(user["role"], "search.view_all"):
            deny(user, "Listing all users' searches needs the search.view_all permission")
        audit.record("SEARCH_HISTORY_VIEWED", detail="scope=all")
        return searches.list_for()
    return searches.list_for(user_id=user["id"])


@router.get("/{search_id}")
def get_one(search_id: str, user: dict = Depends(need("search.view_own"))):
    s = search_access(user, search_id)
    audit.record("SEARCH_VIEWED", target_type="SEARCH", target_id=search_id, search_id=search_id, case_id=s["case_id"])
    s["feedback"] = searches.get_feedback(search_id)
    return s


@router.get("/{search_id}/candidates/{cand_id}")
def view_candidate(search_id: str, cand_id: str, user: dict = Depends(need("search.view_own"))):
    """Opening a candidate's cited evidence is itself audited (EVIDENCE_VIEWED)."""
    s = _completed(user, search_id)
    cand = next((c for c in s["result"]["candidates"] if c["candidate_id"] == cand_id), None)
    if not cand:
        raise HTTPException(404, "Candidate not found")
    audit.record("EVIDENCE_VIEWED", target_type="CANDIDATE", target_id=f"{search_id}/{cand_id}",
                 search_id=search_id, case_id=s["case_id"])
    return cand


@router.delete("/{search_id}")
def delete(search_id: str, _: dict = Depends(need("data.delete"))):
    if not searches.delete(search_id):
        raise HTTPException(404, "Search not found")
    audit.record("DATA_DELETED", target_type="SEARCH", target_id=search_id, search_id=search_id)
    return {"deleted": search_id}


@router.post("/{search_id}/candidates/{cand_id}/feedback")
def feedback(search_id: str, cand_id: str, fb: FeedbackRequest, user: dict = Depends(need("feedback.submit"))):
    s = _completed(user, search_id)
    if cand_id not in {c["candidate_id"] for c in s["result"]["candidates"]}:
        raise HTTPException(404, "Candidate not found")
    searches.add_feedback(search_id, cand_id, fb.verdict, fb.note, user["id"])
    audit.record("CANDIDATE_FEEDBACK", target_type="CANDIDATE", target_id=f"{search_id}/{cand_id}",
                 search_id=search_id, case_id=s["case_id"], detail={"verdict": fb.verdict})
    return {"ok": True}


@router.get("/{search_id}/graph")
def evidence_graph(search_id: str, user: dict = Depends(need("search.view_own"))):
    return graph.build(_completed(user, search_id))


@router.post("/{search_id}/ask")
def ask(search_id: str, q: Question, user: dict = Depends(need("search.view_own"))):
    s = _completed(user, search_id)
    ratelimit.check(f"ask:{user['id']}", config.RATE_LIMIT_PER_HOUR * 4)
    try:
        out = rag.ask(search_id, q.question, get_provider())
    except ValueError as e:
        audit.record("EVIDENCE_QUESTION", target_type="SEARCH", target_id=search_id, search_id=search_id,
                     result="DENIED", detail=str(e))
        raise HTTPException(400, str(e))
    audit.record("EVIDENCE_QUESTION", target_type="SEARCH", target_id=search_id, search_id=search_id,
                 case_id=s["case_id"])
    return out


def _doc(user: dict, search_id: str) -> tuple[dict, dict]:
    s = _completed(user, search_id)
    return s, builder.search_report(s, searches.get_feedback(search_id))


@router.get("/{search_id}/report", response_class=HTMLResponse)
def report_html(search_id: str, user: dict = Depends(need("report.view"))):
    s, doc = _doc(user, search_id)
    body = html.render(doc)
    rid = reports.record("SEARCH", "html", hashlib.sha256(body.encode()).hexdigest(), user["id"],
                         case_id=s["case_id"], search_id=search_id)
    audit.record("REPORT_GENERATED", target_type="REPORT", target_id=rid, search_id=search_id, case_id=s["case_id"])
    return body


@router.get("/{search_id}/report.pdf")
def report_pdf(search_id: str, user: dict = Depends(need("evidence.export"))):
    s, doc = _doc(user, search_id)
    data = pdf.render(doc)
    rid = reports.record("SEARCH", "pdf", hashlib.sha256(data).hexdigest(), user["id"],
                         case_id=s["case_id"], search_id=search_id)
    audit.record("REPORT_EXPORTED", target_type="REPORT", target_id=rid, search_id=search_id, case_id=s["case_id"],
                 detail={"format": "pdf"})
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="search-report-{search_id}.pdf"'})
