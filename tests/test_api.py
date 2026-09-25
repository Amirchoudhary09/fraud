from fastapi.testclient import TestClient

from app.main import app

REQ = {"identity": {"name": "Amir Choudhary", "company": "WASP3D", "college": "GLBITM", "role": "Software Developer"},
       "purpose": "self_check", "acknowledged": True}


def client():
    return TestClient(app)


def test_full_flow_in_mock_mode():
    with client() as c:
        assert c.get("/api/health").json()["mode"] == "mock"
        r = c.post("/api/investigations", json=REQ)
        assert r.status_code == 202
        inv_id = r.json()["id"]

        inv = c.get(f"/api/investigations/{inv_id}").json()  # background task already ran
        assert inv["status"] == "done", inv.get("error")
        cands = inv["result"]["candidates"]
        assert cands[0]["score"] >= cands[-1]["score"]
        assert inv["result"]["mock"] is True

        cid = cands[0]["candidate_id"]
        assert c.post(f"/api/investigations/{inv_id}/candidates/{cid}/feedback", json={"verdict": "correct"}).status_code == 200
        assert c.get(f"/api/investigations/{inv_id}").json()["feedback"] == {cid: "correct"}

        report = c.get(f"/api/investigations/{inv_id}/report")
        assert report.status_code == 200 and "not proof of identity" in report.text and "DEMO DATA" in report.text

        assert any(i["id"] == inv_id for i in c.get("/api/investigations").json())
        assert c.delete(f"/api/investigations/{inv_id}").status_code == 200
        assert c.get(f"/api/investigations/{inv_id}").status_code == 404


def test_requires_acknowledgement():
    with client() as c:
        assert c.post("/api/investigations", json={**REQ, "acknowledged": False}).status_code == 422


def test_blocks_sensitive_request():
    with client() as c:
        bad = {**REQ, "identity": {**REQ["identity"], "role": "home address"}}
        r = c.post("/api/investigations", json=bad)
        assert r.status_code == 400 and "sensitive" in r.json()["detail"]


def test_report_escapes_html():
    with client() as c:
        evil = {**REQ, "identity": {**REQ["identity"], "company": "<script>alert(1)</script>"}}
        inv_id = c.post("/api/investigations", json=evil).json()["id"]
        text = c.get(f"/api/investigations/{inv_id}/report").text
        assert "<script>alert(1)" not in text and "&lt;script&gt;" in text
