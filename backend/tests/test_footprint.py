"""Public-footprint mode: multi-platform discovery, per-account scoring, expansion, history, policy."""
import httpx
import pytest

from app.core import audit_store
from app.providers import gemini
from app.schemas.identity import IdentityInput, Profile, SourceRef
from app.services import footprint, platforms

ID = IdentityInput(name="Amir Choudhary", company="WASP3D", college="GLBITM", role="Software Developer")
REQ = {"identity": ID.model_dump(exclude_none=True), "purpose": "self_check", "acknowledged": True,
       "mode": "footprint", "self_attestation": True}


def src(url):
    return SourceRef(url=url, title="t")


@pytest.fixture(scope="module")
def fp_result(client, admin_h):
    sid = client.post("/api/searches", json=REQ, headers=admin_h).json()["id"]
    s = client.get(f"/api/searches/{sid}", headers=admin_h).json()
    assert s["status"] == "completed", s.get("error")
    return sid, s["result"]


def accounts(fp_result, candidate=None):
    return [a for a in fp_result[1]["footprint"]["accounts"] if candidate in (None, a["candidate_id"])]


# 1. multiple platforms for the same person
def test_multiple_platforms_for_the_same_person(fp_result):
    found = {a["platform"] for a in accounts(fp_result, "C001") if a["status"] == "FOUND"}
    assert {"linkedin", "github", "website", "youtube"} <= found
    assert fp_result[1]["footprint"]["target_candidates"] == ["C001"]


# 2. same username belonging to different people -> separate candidates, never merged
def test_same_username_different_people_are_not_merged(fp_result):
    iedemo = [a for a in accounts(fp_result) if a.get("username") == "iedemo"]
    assert {a["candidate_id"] for a in iedemo} == {"C001", "C002", "C003"}
    tiktok = next(a for a in iedemo if a["platform"] == "tiktok")
    assert tiktok["status"] == "INSUFFICIENT EVIDENCE" and any("name" in c for c in tiktok["contradictions"])
    assert "different person" in tiktok["explanation"]["why_it_may_not_match"][0]


# 3. cross-linked accounts (found by expanding the person's own published links)
def test_cross_linked_account_found_by_expansion(fp_result):
    yt = next(a for a in accounts(fp_result, "C001") if a["platform"] == "youtube")
    assert yt["discovered_via"] == "cross_link" and yt["linked_from"] == "https://portfolio.example.com/iedemo"
    assert yt["status"] == "FOUND" and any(e["field"] == "cross_link" for e in yt["evidence"])
    exp = fp_result[1]["footprint"]["expansion"]
    assert exp["pages_fetched"] >= 1 and exp["leads_followed"] >= 1
    assert exp["stopped_because"] in ("no new public leads", "round budget reached", "lead budget reached")


# 4. contradictory identity evidence
def test_contradictory_evidence_lowers_score(fp_result):
    ig = next(a for a in accounts(fp_result, "C002") if a["platform"] == "instagram")
    assert ig["status"] == "INSUFFICIENT EVIDENCE" and ig["score"] < footprint.POSSIBLE_AT
    assert any(c.startswith("company") for c in ig["contradictions"])
    assert ig["explanation"]["contradicting_sources"] == ["https://www.instagram.com/iedemo"]


# 5. historical account evidence
def test_history_only_for_high_confidence_accounts(fp_result):
    tl = fp_result[1]["footprint"]["timeline"]
    events = {(e["date"], e["event"]) for e in tl}
    assert ("2019-06", "Account created (publicly documented)") in events
    assert ("2021-03", "Website first archived by the Internet Archive") in events
    assert all(e["platform"] != "Reddit" for e in tl)  # INSUFFICIENT accounts contribute no history


# 6. missing platforms are listed, not omitted
def test_every_platform_has_a_status(fp_result):
    rows = {r["platform"]: r["status"] for r in fp_result[1]["footprint"]["platform_status"]}
    assert set(rows) >= {p.key for p in platforms.PLATFORMS} | {"website"}
    assert rows["kaggle"] == "NOT FOUND" and rows["telegram"] == "NOT SEARCHABLE"
    assert rows["linkedin"] == "FOUND" and rows["instagram"] == "INSUFFICIENT EVIDENCE"
    assert set(rows.values()) <= {"FOUND", "POSSIBLE MATCH", "NOT FOUND", "NOT SEARCHABLE", "INSUFFICIENT EVIDENCE"}


# 7. low-confidence candidates / 8. false-positive prevention
def test_username_only_is_never_a_match():
    p = Profile(platform="reddit", username="iedemo", profile_url="https://www.reddit.com/user/iedemo", source=src("x"))
    a = footprint.score_account(IdentityInput(name="Amir Choudhary", username="iedemo"), p, set(), set(), set())
    assert a["status"] == "INSUFFICIENT EVIDENCE" and a["confidence"] == "LOW"
    assert "Only the username matches" in a["explanation"]["why_it_may_not_match"][0]


def test_single_weak_signal_is_only_possible():
    p = Profile(platform="github", display_name="Amir Choudhary", profile_url="https://github.com/x", source=src("u"))
    a = footprint.score_account(ID, p, set(), set(), set())
    assert a["status"] == "POSSIBLE MATCH"


# 9. evidence citation
def test_every_positive_signal_cites_a_source(fp_result):
    for a in accounts(fp_result):
        assert a["source"] and a["source"]["url"]
        for e in a["evidence"]:
            if e["points"] > 0:
                assert e["sources"], (a["platform"], e["field"])


def test_model_cannot_invent_links_or_profiles():
    sources = {"S1": src("https://github.com/iedemo")}
    parsed = {"candidates": [{"display_name": "A", "claims": [{"field": "name", "value": "A", "source_id": "S1"}],
                              "profiles": [
                                  {"source_id": "S1", "platform": "github", "links": ["https://invented.example/x",
                                                                                      "https://real.example/me"],
                                   "events": [{"date": "2022-04", "event": "repo", "source_id": "S1"},
                                              {"date": "last year", "event": "bad date", "source_id": "S1"},
                                              {"date": "2020", "event": "uncited", "source_id": "S9"}]},
                                  {"source_id": "S9", "platform": "x"}]}]}
    c = gemini.parse_candidates(parsed, sources, "see https://real.example/me for more")[0]
    assert len(c.profiles) == 1  # the uncited profile is dropped
    assert c.profiles[0].public_links == ["https://real.example/me"]
    assert [e.date for e in c.profiles[0].events] == ["2022-04"]


def test_grounding_redirects_resolve_to_real_urls():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://www.linkedin.com/in/someone"})
    p = gemini.GeminiProvider("k", "m")
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert p.resolve_source("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc") == \
        "https://www.linkedin.com/in/someone"
    assert p.resolve_source("https://example.org/page") == "https://example.org/page"  # other hosts untouched


def test_social_networks_are_never_fetched():
    assert not platforms.fetchable_url("https://www.instagram.com/someone")
    assert not platforms.fetchable_url("https://www.linkedin.com/in/someone")
    assert platforms.fetchable_url("https://linktr.ee/someone") and platforms.fetchable_url("https://me.example.com/")
    assert gemini.GeminiProvider("k", "m").fetch_public_page("https://www.facebook.com/someone") is None


# 10. graph relationships
def test_graph_has_profile_and_link_edges(client, admin_h, fp_result):
    g = client.get(f"/api/searches/{fp_result[0]}/graph", headers=admin_h).json()
    types = {e["type"] for e in g["edges"]}
    assert {"HAS_PROFILE", "OWNS_WEBSITE", "LINKS_TO"} <= types
    assert all(e["sources"] for e in g["edges"] if e["type"] in ("HAS_PROFILE", "LINKS_TO"))
    cypher = client.get(f"/api/searches/{fp_result[0]}/graph.cypher", headers=admin_h).text
    assert ":Profile" in cypher and "HAS_PROFILE" in cypher


# 11. timeline generation
def test_timeline_is_sorted_and_sourced(fp_result):
    tl = fp_result[1]["footprint"]["timeline"]
    assert [e["date"] for e in tl] == sorted(e["date"] for e in tl)
    assert all(e["source"] and e["source"]["url"] and e["confidence"] in ("HIGH", "MEDIUM", "LOW") for e in tl)


def test_platform_url_classification():
    assert platforms.classify_url("https://www.linkedin.com/in/jane-doe-123/") == ("linkedin", "jane-doe-123")
    assert platforms.classify_url("https://github.com/janedoe") == ("github", "janedoe")
    assert platforms.classify_url("https://www.youtube.com/@jane") == ("youtube", "jane")
    assert platforms.classify_url("https://x.com/jane/status/1") == ("x", None)
    assert platforms.classify_url("https://jane.substack.com/p/post") == ("substack", "jane")
    assert platforms.classify_url("https://jane.dev/about") == ("website", None)


def test_report_has_footprint_sections(client, admin_h, fp_result):
    html = client.get(f"/api/searches/{fp_result[0]}/report", headers=admin_h).text
    for title in ("Executive summary", "Discovered public profiles", "High-confidence profiles", "Possible profiles",
                  "Platform-by-platform results", "Cross-platform connections", "Public account history",
                  "Chronological timeline", "Evidence graph", "Contradictions", "Sources", "Limitations",
                  "Human review required"):
        assert title in html, title


# policy: footprints only for self-checks, consented verification, or incident authors
@pytest.mark.parametrize("override,expect", [
    ({"self_attestation": False}, "confirming that you are the person"),
    ({"purpose": "research"}, "does not allow"),
    ({"purpose": "professional_verification"}, "consent reference"),
    ({"purpose": "harassment_report"}, "reported incident"),
])
def test_footprint_policy(client, admin_h, override, expect):
    r = client.post("/api/searches", json={**REQ, **override}, headers=admin_h)
    assert r.status_code == 403 and expect in r.json()["detail"]
    assert audit_store.query(event_types=["FOOTPRINT_DENIED"], limit=1)


def test_footprint_on_others_needs_role(client, analyst_h, investigator_h):
    body = {**REQ, "purpose": "professional_verification", "consent_reference": "HR-2026-0042 signed"}
    assert client.post("/api/searches", json=body, headers=analyst_h).status_code == 403
    assert client.post("/api/searches", json=body, headers=investigator_h).status_code == 202


def test_standard_mode_is_unchanged(client, analyst_h):
    body = {**REQ, "mode": "standard", "self_attestation": False, "purpose": "research"}
    s = client.get(f"/api/searches/{client.post('/api/searches', json=body, headers=analyst_h).json()['id']}",
                   headers=analyst_h).json()
    assert s["status"] == "completed" and s["result"]["footprint"] is None
    assert [t["agent"] for t in s["result"]["agent_trace"]] == ["search", "evidence", "matching", "report"]
