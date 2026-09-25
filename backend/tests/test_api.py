from app.core import audit_store

REQ = {"identity": {"name": "Amir Choudhary", "company": "WASP3D", "college": "GLBITM", "role": "Software Developer"},
       "purpose": "self_check", "acknowledged": True}


def test_full_search_flow(client, analyst_h, admin_h, investigator_h):
    assert client.get("/api/health").json()["mode"] == "mock"
    r = client.post("/api/searches", json=REQ, headers=analyst_h)
    assert r.status_code == 202
    sid = r.json()["id"]
    assert sid.startswith("SRCH-")

    s = client.get(f"/api/searches/{sid}", headers=analyst_h).json()  # job ran inline
    assert s["status"] == "completed", s.get("error")
    assert s["candidate_count"] == 3 and s["completed_at"] and s["search_type"] == "PUBLIC_IDENTITY"
    res = s["result"]
    assert res["candidates"][0]["score"] >= res["candidates"][-1]["score"]
    assert [t["agent"] for t in res["agent_trace"]] == ["search", "evidence", "matching", "report"]
    assert res["indexed_chunks"] > 0

    # the full audit chain of spec section 5 exists for this search
    types = {e["event_type"] for e in audit_store.query(limit=2000) if e["search_id"] == sid}
    assert {"SEARCH_STARTED", "SEARCH_QUERY_CREATED", "SEARCH_EXECUTED", "SEARCH_RESULTS_RECEIVED",
            "CANDIDATE_CREATED", "SEARCH_COMPLETED", "SEARCH_VIEWED"} <= types

    cid = res["candidates"][0]["candidate_id"]
    assert client.get(f"/api/searches/{sid}/candidates/{cid}", headers=analyst_h).status_code == 200
    assert any(e["event_type"] == "EVIDENCE_VIEWED" and e["target_id"] == f"{sid}/{cid}"
               for e in audit_store.query(limit=50))
    fb = client.post(f"/api/searches/{sid}/candidates/{cid}/feedback", json={"verdict": "correct"}, headers=analyst_h)
    assert fb.status_code == 200
    assert client.get(f"/api/searches/{sid}", headers=analyst_h).json()["feedback"] == {cid: "correct"}

    report = client.get(f"/api/searches/{sid}/report", headers=analyst_h)
    assert report.status_code == 200 and "not proof of identity" in report.text and "DEMO DATA" in report.text
    assert "default-src 'none'" in report.headers["content-security-policy"]
    # analysts can read reports but not export them
    assert client.get(f"/api/searches/{sid}/report.pdf", headers=analyst_h).status_code == 403

    # another user cannot see this search
    assert client.get(f"/api/searches/{sid}", headers=investigator_h).status_code == 403
    assert all(x["id"] != sid for x in client.get("/api/searches", headers=investigator_h).json())
    assert any(x["id"] == sid for x in client.get("/api/searches", headers=analyst_h).json())
    assert any(x["id"] == sid for x in client.get("/api/searches?scope=all", headers=admin_h).json())
    assert client.get("/api/searches?scope=all", headers=analyst_h).status_code == 403

    pdf = client.get(f"/api/searches/{sid}/report.pdf", headers=admin_h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.delete(f"/api/searches/{sid}", headers=analyst_h).status_code == 403
    assert client.delete(f"/api/searches/{sid}", headers=admin_h).status_code == 200
    assert client.get(f"/api/searches/{sid}", headers=admin_h).status_code == 404


def test_user_searched_entity_relationship(client, user_h):
    sid = client.post("/api/searches", json={**REQ, "identity": {"name": "Shahid Example"}}, headers=user_h).json()["id"]
    dash = client.get("/api/me/dashboard", headers=user_h).json()
    rel = next(r for r in dash["relationships"] if r["search_id"] == sid)
    assert rel["relationship_type"] == "SEARCHED" and rel["object_label"] == "Shahid Example"
    assert rel["object_id"].startswith("ENT-")
    # searching the same person again reuses the entity
    sid2 = client.post("/api/searches", json={**REQ, "identity": {"name": "shahid  example"}}, headers=user_h).json()["id"]
    rels = {r["search_id"]: r["object_id"] for r in client.get("/api/me/dashboard", headers=user_h).json()["relationships"]}
    assert rels[sid] == rels[sid2]


def test_graph_and_ask(client, analyst_h):
    sid = client.post("/api/searches", json=REQ, headers=analyst_h).json()["id"]
    g = client.get(f"/api/searches/{sid}/graph", headers=analyst_h).json()
    types = {n["type"] for n in g["nodes"]}
    assert {"Target", "Candidate", "Company", "College", "Source"} <= types
    assert len([n for n in g["nodes"] if n["type"] == "College"]) == 1  # GLBITM merged with full name
    assert {"WORKS_AT", "STUDIED_AT", "CITED_BY", "INPUT_WORKS_AT"} <= {e["type"] for e in g["edges"]}

    a = client.post(f"/api/searches/{sid}/ask", json={"question": "Where does C001 work?"}, headers=analyst_h).json()
    assert a["citations"] and a["answer"]
    bad = client.post(f"/api/searches/{sid}/ask", json={"question": "what is his phone number"}, headers=analyst_h)
    assert bad.status_code == 400


def test_requires_acknowledgement(client, analyst_h):
    assert client.post("/api/searches", json={**REQ, "acknowledged": False}, headers=analyst_h).status_code == 422


def test_blocks_sensitive_request(client, analyst_h):
    bad = {**REQ, "identity": {**REQ["identity"], "role": "home address"}}
    r = client.post("/api/searches", json=bad, headers=analyst_h)
    assert r.status_code == 400 and "sensitive" in r.json()["detail"]


def test_report_escapes_html(client, analyst_h):
    evil = {**REQ, "identity": {**REQ["identity"], "company": "<script>alert(1)</script>"}}
    sid = client.post("/api/searches", json=evil, headers=analyst_h).json()["id"]
    text = client.get(f"/api/searches/{sid}/report", headers=analyst_h).text
    assert "<script>alert(1)" not in text and "&lt;script&gt;" in text


def test_security_headers_and_request_id(client):
    r = client.get("/api/health", headers={"X-Request-ID": "REQ-abc123"})
    assert r.headers["x-request-id"] == "REQ-abc123"
    assert r.headers["x-content-type-options"] == "nosniff" and "max-age" in r.headers["strict-transport-security"]


def test_body_size_limit(client, analyst_h):
    r = client.post("/api/searches", content=b"x" * (13 * 1024 * 1024),
                    headers={**analyst_h, "Content-Type": "application/json"})
    assert r.status_code == 413
