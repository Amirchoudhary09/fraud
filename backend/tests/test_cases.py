import hashlib
import sqlite3

from app.core import config
from app.services.comments import analyze, public_handle
from app.services.evidence import canonical_text

from .conftest import make_user

CASE = {"title": "Threatening replies on launch post", "description": "Several replies on X.",
        "purpose": "harassment_report", "acknowledged": True}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_comment_indicators():
    a = analyze("I will find you and kill you, idiot")
    ind = a["indicators"]
    assert ind["threat_indicator"] and ind["abuse_indicator"] and not ind["spam_indicator"]
    assert a["severity"] == "high" and a["suggested_incident_type"] == "THREAT"
    assert analyze("Great talk, thanks for sharing!")["severity"] == "none"
    assert analyze("tujhe dekh lunga")["indicators"]["threat_indicator"]
    assert analyze("Click here for free money")["suggested_incident_type"] == "SPAM"
    assert analyze("Send me the OTP to claim your reward")["suggested_incident_type"] == "SCAM_INDICATOR"
    assert analyze("This is the official support account, verify your account")["indicators"]["impersonation_indicator"]


def test_public_handle_from_url():
    assert public_handle(None, "https://x.com/some_user/status/123") == ("some_user", "x")
    assert public_handle("@given", "https://www.instagram.com/p/abc/") == ("given", "instagram")
    assert public_handle(None, "https://x.com/status/1") == (None, "x")


def test_canonical_hash_is_stable():
    assert canonical_text("héllo \r\nworld  ") == canonical_text("héllo\nworld")


def test_case_incident_evidence_lifecycle(client, investigator_h, analyst_h, admin_h):
    assert client.post("/api/cases", json={**CASE, "acknowledged": False}, headers=investigator_h).status_code == 422
    case = client.post("/api/cases", json=CASE, headers=investigator_h).json()
    cid = case["id"]
    assert cid.startswith("CASE-") and case["status"] == "open"

    # incident with the original comment -> separate INCIDENT, EVIDENCE and ANALYSIS records
    inc = client.post(f"/api/cases/{cid}/incidents", headers=investigator_h, json={
        "comment_text": "you're dead, watch your back", "source_url": "https://x.com/angry_handle/status/99",
        "content_id": "99", "posted_at": "2026-09-20T10:00:00Z", "description": "Reply under my launch post"}).json()
    assert inc["id"].startswith("INC-") and inc["author_handle"] == "angry_handle" and inc["source_platform"] == "x"
    assert inc["incident_type"] == "THREAT" and inc["severity"] == "high"
    assert inc["analysis"]["indicators"]["threat_indicator"] and inc["target_entity"] == "angry_handle"

    full = client.get(f"/api/cases/{cid}", headers=investigator_h).json()
    ev = full["evidence"][0]
    assert ev["type"] == "PUBLIC_COMMENT" and ev["incident_id"] == inc["id"]
    assert ev["content_hash"] == hashlib.sha256(canonical_text("you're dead, watch your back")).hexdigest()
    assert full["analyses"][0]["evidence_id"] == ev["id"] and full["target_entity"] == "angry_handle"

    # evidence content is encrypted at rest, never stored in plaintext
    with sqlite3.connect(config.DB_PATH) as db:
        stored = db.execute("SELECT content_enc FROM evidence WHERE id = ?", (ev["id"],)).fetchone()[0]
    assert "watch your back" not in stored

    viewed = client.get(f"/api/cases/{cid}/evidence/{ev['id']}", headers=investigator_h).json()
    assert viewed["text"] == "you're dead, watch your back"
    assert client.post(f"/api/cases/{cid}/evidence/{ev['id']}/verify", headers=investigator_h).json()["ok"] is True

    # screenshot evidence with integrity hash; encrypted file on disk
    up = client.post(f"/api/cases/{cid}/evidence/file", headers=investigator_h, data={"incident_id": inc["id"]},
                     files={"file": ("screenshot.png", PNG, "image/png")})
    assert up.status_code == 201 and up.json()["content_hash"] == hashlib.sha256(PNG).hexdigest()
    assert "storage_path" not in up.json()
    with sqlite3.connect(config.DB_PATH) as db:
        path = db.execute("SELECT storage_path FROM evidence WHERE id = ?", (up.json()["id"],)).fetchone()[0]
    assert open(path, "rb").read() != PNG
    dl = client.get(f"/api/cases/{cid}/evidence/{up.json()['id']}/download", headers=investigator_h)
    assert dl.content == PNG and dl.headers["x-evidence-sha256"] == hashlib.sha256(PNG).hexdigest()
    bad = client.post(f"/api/cases/{cid}/evidence/file", headers=investigator_h,
                      files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
    assert bad.status_code == 400

    # tampering with stored evidence is detected
    with sqlite3.connect(config.DB_PATH) as db:
        db.execute("UPDATE evidence SET content_hash = ? WHERE id = ?", ("0" * 64, ev["id"]))
    v = client.post(f"/api/cases/{cid}/evidence/{ev['id']}/verify", headers=investigator_h).json()
    assert v["ok"] is False and v["current_hash"] != v["original_hash"]
    sec = client.get("/api/admin/security-events", headers=admin_h).json()
    assert any(e["type"] == "EVIDENCE_INTEGRITY_FAILED" and e["severity"] == "critical" for e in sec)

    # incident -> author handle -> public web search -> identity resolution
    r = client.post(f"/api/cases/{cid}/incidents/{inc['id']}/investigate", json={}, headers=investigator_h)
    assert r.status_code == 202
    s = client.get(f"/api/searches/{r.json()['id']}", headers=investigator_h).json()
    assert s["status"] == "completed" and s["search_type"] == "INCIDENT_AUTHOR" and s["case_id"] == cid
    assert s["input"]["username"] == "angry_handle"

    no_handle = client.post(f"/api/cases/{cid}/incidents", json={"incident_type": "SPAM", "description": "x"},
                            headers=investigator_h).json()
    assert client.post(f"/api/cases/{cid}/incidents/{no_handle['id']}/investigate", json={},
                       headers=investigator_h).status_code == 400

    # timeline covers the whole chain, oldest first
    tl = [t["event_type"] for t in client.get(f"/api/cases/{cid}/timeline", headers=investigator_h).json()]
    for t in ("CASE_CREATED", "INCIDENT_CREATED", "EVIDENCE_CAPTURED", "ANALYSIS_COMPLETED", "SEARCH_STARTED",
              "CANDIDATE_CREATED", "SEARCH_COMPLETED"):
        assert t in tl, t
    assert tl.index("CASE_CREATED") < tl.index("INCIDENT_CREATED") < tl.index("SEARCH_COMPLETED")

    report = client.get(f"/api/cases/{cid}/report", headers=investigator_h).text
    for section in ("Incident information", "Original content", "watch your back", "Evidence collected",
                    hashlib.sha256(PNG).hexdigest(), "AI content analysis", "Public profile information",
                    "Evidence timeline", "not proof of identity"):
        assert section in report, section
    assert client.get(f"/api/cases/{cid}/report.pdf", headers=investigator_h).content.startswith(b"%PDF")
    kinds = {(r["kind"], r["format"]) for r in client.get(f"/api/cases/{cid}", headers=investigator_h).json()["reports"]}
    assert ("CASE", "html") in kinds and ("CASE", "pdf") in kinds

    assert client.patch(f"/api/cases/{cid}", json={"status": "under_review"},
                        headers=investigator_h).json()["status"] == "under_review"
    assert client.delete(f"/api/cases/{cid}", headers=investigator_h).status_code == 403
    assert client.delete(f"/api/cases/{cid}", headers=admin_h).status_code == 200
    assert client.get(f"/api/cases/{cid}", headers=admin_h).status_code == 404
    assert client.get(f"/api/searches/{r.json()['id']}", headers=admin_h).status_code == 404


def test_case_level_access_control(client, admin_h, investigator_h):
    other = make_user(client, admin_h, "investigator", "other-investigator")
    cid = client.post("/api/cases", json=CASE, headers=investigator_h).json()["id"]

    # same role, not a member -> denied and audited
    assert client.get(f"/api/cases/{cid}", headers=other).status_code == 403
    assert all(c["id"] != cid for c in client.get("/api/cases", headers=other).json())

    # owner grants time-limited viewer access
    members = client.post(f"/api/cases/{cid}/members", json={"email": "other-investigator@test.local",
                                                            "access": "viewer", "expires_hours": 2},
                          headers=investigator_h).json()
    grant = next(m for m in members if m["email"] == "other-investigator@test.local")
    assert grant["expires_at"]
    assert client.get(f"/api/cases/{cid}", headers=other).status_code == 200
    # viewer cannot edit
    assert client.post(f"/api/cases/{cid}/incidents", json={"incident_type": "SPAM"}, headers=other).status_code == 403
    client.delete(f"/api/cases/{cid}/members/{grant['id']}", headers=investigator_h)
    assert client.get(f"/api/cases/{cid}", headers=other).status_code == 403

    # super_admin can open it, but that access is audited and alerted
    assert client.get(f"/api/cases/{cid}", headers=admin_h).status_code == 200
    sec = client.get("/api/admin/security-events", headers=admin_h).json()
    assert any(e["type"] == "ADMIN_CASE_ACCESS" for e in sec)

    history = client.get(f"/api/cases/{cid}/access-history", headers=investigator_h).json()
    kinds = [h["event_type"] for h in history]
    assert "CASE_ACCESS_GRANTED" in kinds and "CASE_ACCESS_REVOKED" in kinds and "AUTHZ_DENIED" in kinds
    assert "ADMIN_CASE_ACCESS" in kinds


def test_break_glass(client, admin_h, investigator_h, secadmin_h):
    requester = make_user(client, admin_h, "analyst", "bg-analyst")
    cid = client.post("/api/cases", json=CASE, headers=investigator_h).json()["id"]
    assert client.get(f"/api/cases/{cid}", headers=requester).status_code == 403
    assert client.post(f"/api/cases/{cid}/break-glass", json={"reason": "too short"}, headers=requester).status_code == 422
    bg = client.post(f"/api/cases/{cid}/break-glass", headers=requester,
                     json={"reason": "Credible threat reported to police; need immediate access to evidence."}).json()
    assert bg["status"] == "pending"
    assert client.post(f"/api/admin/break-glass/{bg['id']}", json={"approve": True}, headers=requester).status_code == 403
    ok = client.post(f"/api/admin/break-glass/{bg['id']}", json={"approve": True, "hours": 1}, headers=secadmin_h).json()
    assert ok["status"] == "approved" and ok["expires_at"]
    assert client.get(f"/api/cases/{cid}", headers=requester).status_code == 200
    sec = {e["type"] for e in client.get("/api/admin/security-events", headers=secadmin_h).json()}
    assert {"BREAK_GLASS_REQUESTED", "BREAK_GLASS_APPROVED"} <= sec


def test_url_evidence_is_ssrf_protected(client, investigator_h):
    cid = client.post("/api/cases", json=CASE, headers=investigator_h).json()["id"]
    for url in ("http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data/", "http://localhost:8000/api",
                "file:///etc/passwd", "http://10.0.0.5/", "https://example.com:8443/", "http://user:pw@example.com/"):
        r = client.post(f"/api/cases/{cid}/evidence/url", json={"url": url}, headers=investigator_h)
        assert r.status_code in (400, 422), (url, r.text)
