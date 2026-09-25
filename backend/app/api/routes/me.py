from fastapi import APIRouter, Depends

from ...core import permissions
from ...repositories import cases, entities, searches
from ..deps import current_user

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("/dashboard")
def my_dashboard(user: dict = Depends(current_user)):
    """User dashboard: my searches (who/what/when/case/status), my cases, my relationships."""
    view_all = permissions.has(user["role"], "case.view_all")
    return {
        "user": user,
        "searches": searches.list_for(user_id=user["id"], limit=50),
        "cases": cases.list_visible(None if view_all else user["id"], limit=50),
        "relationships": entities.relationships("USER", user["id"], limit=50),
    }
