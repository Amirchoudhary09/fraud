from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core import audit_store, config
from ...core.database import ago, in_future
from ...evaluation import dataset, metrics
from ...repositories import cases, evidence, incidents, searches, security_events, users
from ...services import audit, calibration, retention
from ..deps import need
from ..middleware import error_counts

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- audit plane -----------------------------------------------------------------------

@router.get("/audit")
def audit_log(limit: int = 200, event_type: str | None = None, actor_user_id: int | None = None,
              case_id: str | None = None, _: dict = Depends(need("audit.view"))):
    audit.record("AUDIT_VIEWED", detail={"event_type": event_type, "actor": actor_user_id, "case_id": case_id})
    return audit_store.query(case_id=case_id, actor_user_id=actor_user_id,
                             event_types=[event_type] if event_type else None, limit=min(limit, 2000))


@router.post("/audit/verify")
def verify_audit(_: dict = Depends(need("audit.verify"))):
    result = audit_store.verify()
    audit.record("AUDIT_VERIFIED" if result["ok"] else "AUDIT_CHAIN_BROKEN",
                 result="SUCCESS" if result["ok"] else "FAILED", detail=result)
    return result


# --- security monitoring ---------------------------------------------------------------

@router.get("/dashboard")
def dashboard(_: dict = Depends(need("security.view"))):
    day = ago(hours=24)
    return {
        "active_users": users.count(active_only=True),
        "active_cases": cases.count_active(),
        "searches_24h": searches.count_since(day),
        "incidents_24h": incidents.count_since(day),
        "evidence_captured_24h": evidence.count_since(day),
        "failed_logins_24h": audit_store.count(event_types=["AUTH_LOGIN_FAILED"], since=day),
        "authz_denied_24h": audit_store.count(event_types=["AUTHZ_DENIED"], since=day),
        "open_security_events": security_events.count_open(),
        "pending_break_glass": len(cases.list_break_glass("pending")),
        "api_errors": dict(error_counts),
        "audit_integrity": audit_store.verify(),
    }


@router.get("/security-events")
def list_security_events(status: str | None = None, _: dict = Depends(need("security.view"))):
    return security_events.list_recent(status)


class SecurityEventUpdate(BaseModel):
    status: Literal["acknowledged", "resolved"]


@router.patch("/security-events/{event_id}")
def update_security_event(event_id: str, body: SecurityEventUpdate, user: dict = Depends(need("security.manage"))):
    if not security_events.set_status(event_id, body.status, user["id"]):
        raise HTTPException(404, "Security event not found")
    audit.record("SECURITY_EVENT_UPDATED", target_type="SECURITY_EVENT", target_id=event_id,
                 detail={"status": body.status})
    return {"ok": True}


# --- break-glass -----------------------------------------------------------------------

@router.get("/break-glass")
def list_break_glass(status: str | None = None, _: dict = Depends(need("break_glass.approve"))):
    return cases.list_break_glass(status)


class Decision(BaseModel):
    approve: bool
    hours: int | None = None


@router.post("/break-glass/{bid}")
def decide_break_glass(bid: str, body: Decision, user: dict = Depends(need("break_glass.approve"))):
    req = cases.get_break_glass(bid)
    if not req:
        raise HTTPException(404, "Request not found")
    if req["status"] != "pending":
        raise HTTPException(409, f"Request already {req['status']}")
    if req["user_id"] == user["id"]:
        raise HTTPException(400, "You cannot approve your own break-glass request")
    if body.approve:
        hours = min(body.hours or config.BREAK_GLASS_HOURS, 72)
        expires = in_future(hours=hours)
        cases.grant(req["case_id"], req["user_id"], "viewer", user["id"], "break_glass", expires)
        cases.decide_break_glass(bid, "approved", user["id"], expires)
        audit.record("BREAK_GLASS_APPROVED", target_type="BREAK_GLASS", target_id=bid, case_id=req["case_id"],
                     detail={"for_user": req["user_id"], "hours": hours})
    else:
        cases.decide_break_glass(bid, "denied", user["id"], None)
        audit.record("BREAK_GLASS_DENIED", target_type="BREAK_GLASS", target_id=bid, case_id=req["case_id"])
    return cases.get_break_glass(bid)


# --- evaluation, calibration, retention -------------------------------------------------

@router.get("/eval-dataset")
def eval_dataset(_: dict = Depends(need("admin.evaluate"))):
    audit.record("EVAL_DATASET_EXPORTED")
    return dataset.from_feedback()


def _stored_rows() -> list[dict]:
    """Rows with the stored (hybrid) scores that the reviewers actually saw."""
    return [{"case": case["id"], "candidate": c["candidate_id"], "label": c["label"], "score": c["score"],
             "status": {}, "coverage": 0.0}
            for case in dataset.from_feedback()["cases"] for c in case["candidates"]]


@router.get("/evaluation")
def evaluation(threshold: int = 75, _: dict = Depends(need("admin.evaluate"))):
    rows = metrics.score_dataset(dataset.from_feedback()["cases"])
    cal = calibration.load(config.CALIBRATION_PATH, config.MIN_CALIBRATION_LABELS)
    return {
        "labels": len(rows),
        "rules_only": metrics.metrics(rows, threshold, cal) if rows else None,
        "stored_scores": metrics.metrics(_stored_rows(), threshold, cal) if rows else None,
        "suggested_weights": metrics.suggest_weights(rows) if rows else None,
        "calibration": cal.to_json() if cal else None,
        "min_calibration_labels": config.MIN_CALIBRATION_LABELS,
        "note": "Reviewer verdicts are the ground truth here. Numbers are only meaningful on a "
                "representative, audited set of labels.",
    }


class CalibrateRequest(BaseModel):
    method: Literal["platt", "isotonic"] = "platt"


@router.post("/calibrate")
def calibrate(body: CalibrateRequest, _: dict = Depends(need("admin.evaluate"))):
    rows = _stored_rows()
    try:
        cal = calibration.Calibrator.fit([r["score"] for r in rows], [r["label"] for r in rows], body.method)
    except ValueError as e:
        raise HTTPException(400, str(e))
    calibration.save(cal, config.CALIBRATION_PATH)
    active = cal.n >= config.MIN_CALIBRATION_LABELS
    audit.record("CALIBRATION_FITTED", detail={"method": body.method, "n": cal.n, "active": active})
    return {"calibration": cal.to_json(), "active": active,
            "message": None if active else f"Saved, but only used after {config.MIN_CALIBRATION_LABELS} labels."}


@router.post("/retention/purge")
def purge(_: dict = Depends(need("data.delete"))):
    return retention.purge() | {"retention_days": config.RETENTION_DAYS}
