"""Data retention for application data (cases, searches, evidence files).

The audit log is deliberately out of scope: it lives in its own append-only store and is
retained under the organisation's documented audit policy, not by this job.
"""
from ..core import config
from ..core.database import ago
from ..repositories import cases, searches
from ..repositories import evidence as evidence_repo
from . import audit, storage


def delete_case(case_id: str) -> bool:
    deleted, search_ids, paths = cases.delete(case_id)
    for sid in search_ids:
        searches.delete(sid)
    for p in paths:
        if not evidence_repo.path_in_use(p):
            storage.remove(p)
    return deleted


def purge(days: int | None = None) -> dict:
    days = config.RETENTION_DAYS if days is None else days
    if days <= 0:
        return {"cases": 0, "searches": 0}
    cutoff = ago(days=days)
    case_ids = cases.older_than(cutoff)
    for cid in case_ids:
        delete_case(cid)
    search_ids = searches.older_than(cutoff)
    for sid in search_ids:
        searches.delete(sid)
    if case_ids or search_ids:
        audit.record("RETENTION_PURGE", detail={"days": days, "cases": len(case_ids), "searches": len(search_ids)})
    return {"cases": len(case_ids), "searches": len(search_ids)}
