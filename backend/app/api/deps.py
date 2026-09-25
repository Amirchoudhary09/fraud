"""Authentication and permission checks. Every protected endpoint depends on `need(permission)`
or `current_user`; denials are written to the audit log (AUTHZ_DENIED) and feed monitoring.

Auth dependencies are async on purpose: they run in the request's own context, so the actor
id they set is visible to the (threadpool) endpoint and to every audit event it writes."""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..core import config, context, permissions
from ..core.security import decode_token
from ..repositories import users
from ..services import audit

_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")  # set by Railway's proxy / the frontend BFF
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _authenticate(cred: HTTPAuthorizationCredentials | None) -> dict:
    claims = decode_token(cred.credentials) if cred else None
    user = users.get(int(claims["sub"])) if claims else None
    if not user or user["status"] != "active":
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    context.actor_id.set(user["id"])
    return user


async def user_allow_pending_mfa(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """For MFA enrolment endpoints: authenticated, even if MFA is required but not yet set up."""
    return _authenticate(cred)


async def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    user = _authenticate(cred)
    if user["role"] in config.MFA_REQUIRED_ROLES and not user["mfa_enabled"]:
        raise HTTPException(403, "MFA enrolment is required for your role. Set it up under Account.")
    return user


def deny(user: dict, reason: str, target_type: str | None = None, target_id: str | None = None,
         case_id: str | None = None, status: int = 403):
    audit.record("AUTHZ_DENIED", target_type=target_type, target_id=target_id, case_id=case_id,
                 result="DENIED", detail=reason, actor_user_id=user["id"])
    raise HTTPException(status, reason)


def need(permission: str):
    async def dep(user: dict = Depends(current_user)) -> dict:
        if not permissions.has(user["role"], permission):
            deny(user, f"Your role ({user['role']}) lacks the '{permission}' permission")
        return user
    return dep
