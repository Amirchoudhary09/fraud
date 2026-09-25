from app.core import audit_store, permissions
from app.core.security import hash_password, totp_now, verify_password, verify_totp

from .conftest import bearer

REQ = {"identity": {"name": "Amir Choudhary"}, "purpose": "self_check", "acknowledged": True}


def test_password_hashing():
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass" and verify_password("s3cret-pass", h) and not verify_password("wrong", h)


def test_totp_rfc6238():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # RFC 6238 test key "12345678901234567890"
    assert totp_now(secret, at=59) == "287082"
    assert verify_totp(secret, totp_now(secret)) and not verify_totp(secret, "000000x")


def test_setup_only_once(client, admin_h):
    assert client.get("/api/auth/status").json()["needs_setup"] is False
    assert client.post("/api/auth/setup", json={"email": "x@test.local", "password": "another-pass1"}).status_code == 409


def test_login_me_and_permissions(client, admin_h):
    assert client.post("/api/auth/login", json={"email": "admin@test.local", "password": "wrong-pass"}).status_code == 401
    s = client.post("/api/auth/login", json={"email": "ADMIN@test.local", "password": "admin-pass-123"}).json()
    assert s["expires_in"] == 15 * 60 and s["refresh_token"]
    me = client.get("/api/auth/me", headers=bearer(s["access_token"])).json()
    assert me["role"] == "super_admin" and "password_hash" not in me and "mfa_secret_enc" not in me
    assert "audit.view" in me["permissions"] and me["last_login_at"]


def test_refresh_rotation_and_reuse_detection(client, admin_h):
    s = client.post("/api/auth/login", json={"email": "admin@test.local", "password": "admin-pass-123"}).json()
    s2 = client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]}).json()
    assert s2["refresh_token"] != s["refresh_token"]
    # replaying the old token revokes the whole session, including the new token
    assert client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": s2["refresh_token"]}).status_code == 401
    assert any(e["event_type"] == "REFRESH_TOKEN_REUSE" for e in audit_store.query(limit=20))


def test_logout_revokes_refresh(client, admin_h):
    s = client.post("/api/auth/login", json={"email": "admin@test.local", "password": "admin-pass-123"}).json()
    client.post("/api/auth/logout", json={"refresh_token": s["refresh_token"]})
    assert client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401


def test_mfa_enrolment_and_login(client, admin_h):
    cred = {"email": "mfa@test.local", "password": "mfa-pass-12345"}
    client.post("/api/users", json={**cred, "role": "analyst"}, headers=admin_h)
    h = bearer(client.post("/api/auth/login", json=cred).json()["access_token"])
    secret = client.post("/api/auth/mfa/setup", headers=h).json()["secret"]
    assert client.post("/api/auth/mfa/confirm", json={"code": "123456"}, headers=h).status_code == 400
    assert client.post("/api/auth/mfa/confirm", json={"code": totp_now(secret)}, headers=h).status_code == 200

    step1 = client.post("/api/auth/login", json=cred).json()
    assert step1["mfa_required"] and "access_token" not in step1
    bad = client.post("/api/auth/login/mfa", json={"mfa_token": step1["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login/mfa", json={"mfa_token": step1["mfa_token"], "code": totp_now(secret)})
    assert ok.status_code == 200 and ok.json()["user"]["mfa_enabled"] == 1
    # an MFA challenge token is not an access token
    assert client.get("/api/auth/me", headers=bearer(step1["mfa_token"])).status_code == 401


def test_requires_auth(client):
    assert client.get("/api/searches").status_code == 401
    assert client.get("/api/searches", headers=bearer("garbage")).status_code == 401


def test_rbac_matrix(client, user_h, analyst_h, auditor_h, secadmin_h, admin_h):
    assert client.post("/api/searches", json=REQ, headers=user_h).status_code == 202  # users may search
    assert client.post("/api/cases", json={"title": "x case", "acknowledged": True}, headers=user_h).status_code == 403
    assert client.post("/api/searches", json=REQ, headers=auditor_h).status_code == 403
    assert client.get("/api/admin/audit", headers=analyst_h).status_code == 403
    assert client.get("/api/admin/audit", headers=auditor_h).status_code == 200
    assert client.get("/api/users", headers=secadmin_h).status_code == 200
    assert client.get("/api/users", headers=auditor_h).status_code == 403
    denied = [e for e in audit_store.query(event_types=["AUTHZ_DENIED"], limit=50)]
    assert len(denied) >= 3 and all(e["result"] == "DENIED" for e in denied)


def test_nobody_can_delete_audit_logs():
    for role in permissions.ROLES:
        assert not permissions.has(role, "audit.delete") and not permissions.has(role, "audit.modify")


def test_security_admin_cannot_mint_super_admins(client, secadmin_h):
    r = client.post("/api/users", json={"email": "sneaky@test.local", "password": "sneaky-pass-1", "role": "super_admin"},
                    headers=secadmin_h)
    assert r.status_code == 403


def test_cannot_change_own_account(client, admin_h):
    me = client.get("/api/auth/me", headers=admin_h).json()
    assert client.patch(f"/api/users/{me['id']}", json={"status": "disabled"}, headers=admin_h).status_code == 400


def test_disabled_user_is_rejected_and_sessions_revoked(client, admin_h):
    cred = {"email": "temp@test.local", "password": "temp-pass-123"}
    uid = client.post("/api/users", json={**cred, "role": "user"}, headers=admin_h).json()["id"]
    s = client.post("/api/auth/login", json=cred).json()
    assert client.get("/api/auth/me", headers=bearer(s["access_token"])).status_code == 200
    client.patch(f"/api/users/{uid}", json={"status": "disabled"}, headers=admin_h)
    assert client.get("/api/auth/me", headers=bearer(s["access_token"])).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": s["refresh_token"]}).status_code == 401
    types = {e["event_type"] for e in audit_store.query(limit=30)}
    assert "USER_STATUS_CHANGED" in types
