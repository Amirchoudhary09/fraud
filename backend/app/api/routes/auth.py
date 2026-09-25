import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from ...core import config, crypto, permissions, ratelimit
from ...core.database import now
from ...core.security import (create_access_token, create_mfa_token, decode_token, hash_password, hash_refresh_token,
                              new_refresh_token, new_totp_secret, totp_uri, verify_password, verify_totp)
from ...repositories import users
from ...schemas.auth import Credentials, LoginRequest, MfaCode, MfaLogin, NewUser, RefreshRequest, UserUpdate
from ...services import audit
from ..deps import client_ip, current_user, deny, need, user_allow_pending_mfa

router = APIRouter(tags=["auth"])


def _session(user: dict, family_id: str | None = None) -> dict:
    raw, digest = new_refresh_token()
    users.store_refresh(user["id"], digest, config.REFRESH_TOKEN_DAYS, family_id)
    return {"access_token": create_access_token(user), "refresh_token": raw, "token_type": "bearer",
            "expires_in": config.ACCESS_TOKEN_MINUTES * 60, "user": _me(user)}


def _me(user: dict) -> dict:
    return {**user, "permissions": permissions.of(user["role"]),
            "mfa_required": user["role"] in config.MFA_REQUIRED_ROLES}


@router.get("/api/auth/status")
def status():
    return {"needs_setup": users.count() == 0, "mfa_required_roles": config.MFA_REQUIRED_ROLES}


@router.post("/api/auth/setup", status_code=201)
def setup(cred: Credentials):
    """Creates the first account (super_admin). Disabled once any user exists."""
    if users.count() > 0:
        raise HTTPException(409, "Setup already done. Ask an administrator for an account.")
    user = users.create(cred.email, hash_password(cred.password), "super_admin")
    audit.record("AUTH_SETUP", target_type="USER", target_id=str(user["id"]), actor_user_id=user["id"])
    return _session(user)


@router.post("/api/auth/login")
def login(body: LoginRequest, request: Request):
    ratelimit.check(f"login:{client_ip(request)}", 30)
    row = users.get_by_email_private(body.email)
    if not row or row["status"] != "active" or not verify_password(body.password, row["password_hash"]):
        audit.record("AUTH_LOGIN_FAILED", target_type="USER", target_id=str(row["id"]) if row else None,
                     result="FAILED", detail="bad credentials or disabled account")
        raise HTTPException(401, "Wrong email or password")
    if row["mfa_enabled"]:
        return {"mfa_required": True, "mfa_token": create_mfa_token(row)}
    users.update(row["id"], last_login_at=now())
    audit.record("AUTH_LOGIN_SUCCESS", target_type="USER", target_id=str(row["id"]), actor_user_id=row["id"])
    return _session(users.get(row["id"]))


@router.post("/api/auth/login/mfa")
def login_mfa(body: MfaLogin, request: Request):
    ratelimit.check(f"mfa:{client_ip(request)}", 30)
    claims = decode_token(body.mfa_token, "mfa")
    row = users.get_private(int(claims["sub"])) if claims else None
    if not row or row["status"] != "active" or not row["mfa_secret_enc"] or \
            not verify_totp(crypto.decrypt_text(row["mfa_secret_enc"]), body.code):
        audit.record("AUTH_LOGIN_FAILED", target_type="USER", target_id=str(row["id"]) if row else None,
                     result="FAILED", detail="bad MFA code")
        raise HTTPException(401, "Invalid or expired MFA code")
    users.update(row["id"], last_login_at=now())
    audit.record("AUTH_LOGIN_SUCCESS", target_type="USER", target_id=str(row["id"]), actor_user_id=row["id"],
                 detail="mfa")
    return _session(users.get(row["id"]))


@router.post("/api/auth/refresh")
def refresh(body: RefreshRequest):
    tok = users.get_refresh(hash_refresh_token(body.refresh_token))
    if not tok:
        raise HTTPException(401, "Invalid refresh token")
    if tok["revoked_at"]:
        # A rotated token came back: it was stolen or replayed. Kill the whole session.
        users.revoke_family(tok["family_id"])
        audit.record("REFRESH_TOKEN_REUSE", target_type="USER", target_id=str(tok["user_id"]),
                     actor_user_id=tok["user_id"], result="DENIED")
        raise HTTPException(401, "Session revoked. Please sign in again.")
    user = users.get(tok["user_id"])
    if tok["expires_at"] < now() or not user or user["status"] != "active":
        users.revoke_family(tok["family_id"])
        raise HTTPException(401, "Session expired. Please sign in again.")
    session = _session(user, tok["family_id"])
    new = users.get_refresh(hash_refresh_token(session["refresh_token"]))
    users.rotate_refresh(tok["id"], new["id"])
    audit.record("AUTH_TOKEN_REFRESHED", target_type="USER", target_id=str(user["id"]), actor_user_id=user["id"])
    return session


@router.post("/api/auth/logout")
def logout(body: RefreshRequest):
    tok = users.get_refresh(hash_refresh_token(body.refresh_token))
    if tok:
        users.revoke_family(tok["family_id"])
        audit.record("AUTH_LOGOUT", target_type="USER", target_id=str(tok["user_id"]), actor_user_id=tok["user_id"])
    return {"ok": True}


@router.get("/api/auth/me")
def me(user: dict = Depends(user_allow_pending_mfa)):
    return _me(user)


# --- MFA -------------------------------------------------------------------------------

@router.post("/api/auth/mfa/setup")
def mfa_setup(user: dict = Depends(user_allow_pending_mfa)):
    if user["mfa_enabled"]:
        raise HTTPException(409, "MFA is already enabled")
    secret = new_totp_secret()
    users.update(user["id"], mfa_secret_enc=crypto.encrypt_text(secret))
    return {"secret": secret, "otpauth_uri": totp_uri(secret, user["email"])}


@router.post("/api/auth/mfa/confirm")
def mfa_confirm(body: MfaCode, user: dict = Depends(user_allow_pending_mfa)):
    row = users.get_private(user["id"])
    if not row["mfa_secret_enc"] or not verify_totp(crypto.decrypt_text(row["mfa_secret_enc"]), body.code):
        raise HTTPException(400, "Code does not match. Check the time on your phone and try again.")
    users.update(user["id"], mfa_enabled=1)
    audit.record("MFA_ENROLLED", target_type="USER", target_id=str(user["id"]))
    return {"mfa_enabled": True}


@router.post("/api/auth/mfa/disable")
def mfa_disable(body: MfaCode, user: dict = Depends(current_user)):
    row = users.get_private(user["id"])
    if not row["mfa_enabled"] or not verify_totp(crypto.decrypt_text(row["mfa_secret_enc"]), body.code):
        raise HTTPException(400, "Invalid code")
    if user["role"] in config.MFA_REQUIRED_ROLES:
        raise HTTPException(400, "MFA is mandatory for your role")
    users.clear_mfa(user["id"])
    audit.record("MFA_DISABLED", target_type="USER", target_id=str(user["id"]))
    return {"mfa_enabled": False}


# --- user management -------------------------------------------------------------------

@router.get("/api/users")
def list_users(_: dict = Depends(need("users.manage"))):
    return users.list_all()


@router.post("/api/users", status_code=201)
def create_user(body: NewUser, me: dict = Depends(need("users.manage"))):
    if body.role == "super_admin" and me["role"] != "super_admin":
        deny(me, "Only a super_admin can create another super_admin")
    try:
        user = users.create(body.email, hash_password(body.password), body.role)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A user with this email already exists")
    audit.record("USER_CREATED", target_type="USER", target_id=str(user["id"]), detail={"role": user["role"]})
    return user


@router.patch("/api/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, me: dict = Depends(need("users.manage"))):
    if user_id == me["id"]:
        raise HTTPException(400, "You cannot change your own role or status")
    target = users.get(user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if me["role"] != "super_admin" and ("super_admin" in (body.role, target["role"])):
        deny(me, "Only a super_admin can change super_admin accounts", "USER", str(user_id))
    user = users.update(user_id, role=body.role, status=body.status)
    if body.role and body.role != target["role"]:
        audit.record("USER_ROLE_CHANGED", target_type="USER", target_id=str(user_id),
                     detail={"from": target["role"], "to": body.role})
    if body.status and body.status != target["status"]:
        if body.status == "disabled":
            users.revoke_all_for_user(user_id)
        audit.record("USER_STATUS_CHANGED", target_type="USER", target_id=str(user_id),
                     detail={"from": target["status"], "to": body.status})
    return user


@router.post("/api/users/{user_id}/reset-mfa")
def reset_mfa(user_id: int, me: dict = Depends(need("users.manage"))):
    if not users.get(user_id):
        raise HTTPException(404, "User not found")
    users.clear_mfa(user_id)
    users.revoke_all_for_user(user_id)
    audit.record("MFA_RESET", target_type="USER", target_id=str(user_id))
    return {"ok": True}
