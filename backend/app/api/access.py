"""Object-level authorization: case membership and search ownership.

A role permission is necessary but not sufficient: to see a case's content the user must be
an active member (owner / editor / viewer, including time-limited break-glass grants).
super_admin can open any case, but each such access is audited as ADMIN_CASE_ACCESS and
raises a security event, so admin access is never silent.
"""
from fastapi import HTTPException

from ..core import permissions
from ..repositories import cases, searches
from ..services import audit
from .deps import deny

_RANK = {"viewer": 1, "editor": 2, "owner": 3}


def case_access(user: dict, case_id: str, need: str = "viewer") -> dict:
    case = cases.get(case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    m = cases.membership(case_id, user["id"])
    if m and _RANK[m["access"]] >= _RANK[need]:
        return case
    if permissions.has(user["role"], "case.view_all"):
        audit.record("ADMIN_CASE_ACCESS", target_type="CASE", target_id=case_id, case_id=case_id,
                     detail=f"need={need} membership={m['access'] if m else 'none'}")
        return case
    deny(user, "You do not have access to this case" if not m else f"This action needs {need} access",
         target_type="CASE", target_id=case_id, case_id=case_id)


def search_access(user: dict, search_id: str) -> dict:
    s = searches.get(search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    if s["user_id"] == user["id"] or permissions.has(user["role"], "search.view_all"):
        return s
    if s["case_id"] and cases.membership(s["case_id"], user["id"]):
        return s
    deny(user, "You do not have access to this search", target_type="SEARCH", target_id=search_id,
         case_id=s["case_id"])
