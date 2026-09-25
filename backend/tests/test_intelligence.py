"""Hybrid matching, agents, calibration and evaluation."""
from pathlib import Path

from app.agents.supervisor import route
from app.evaluation import metrics
from app.providers.mock import MockProvider
from app.schemas.identity import IdentityInput
from app.services.calibration import Calibrator
from app.services.matching import rank

ID = IdentityInput(name="Amir Choudhary", company="WASP3D", college="GLBITM", role="Software Developer")
SAMPLE = Path(__file__).resolve().parents[1] / "eval" / "sample_dataset.json"


def test_hybrid_signals_are_added_and_capped():
    p = MockProvider()
    ranked = rank(ID, p.extract_candidates(ID, []), p)
    top = ranked[0]
    fields = {s.field: s for s in top.signals}
    assert fields["semantic"].points <= 10 and fields["llm"].status == "match"
    assert ranked[1].signals[-1].field == "llm" and ranked[1].signals[-1].status == "mismatch"
    assert [c.candidate_id for c in ranked] == ["C001", "C002", "C003"]


def test_judge_failure_falls_back_to_rules():
    class Broken(MockProvider):
        def judge(self, identity, cand):
            raise RuntimeError("quota exceeded")
    ranked = rank(ID, Broken().extract_candidates(ID, []), Broken())
    assert all(s.field != "llm" for c in ranked for s in c.signals)


def test_supervisor_routing():
    assert route({}) == "search"
    assert route({"results": [1], "candidates": None}) == "evidence"
    assert route({"results": [1], "candidates": [], "search_rounds": 1}) == "search"  # broaden
    assert route({"results": [1], "candidates": [], "search_rounds": 2}) == "matching"  # give up
    assert route({"results": [1], "candidates": [1], "scored": None}) == "matching"
    assert route({"results": [1], "candidates": [1], "scored": [1]}) == "report"
    assert route({"results": [1], "candidates": [1], "scored": [1], "reported": True}) == "__end__"


def test_supervisor_broadens_search_when_nothing_found(client, analyst_h, monkeypatch):
    calls = {"extract": 0}

    class FirstRoundEmpty(MockProvider):
        def extract_candidates(self, identity, results):
            calls["extract"] += 1
            return [] if calls["extract"] == 1 else super().extract_candidates(identity, results)

    import app.agents.supervisor as sup
    monkeypatch.setattr(sup, "get_provider", lambda: FirstRoundEmpty())
    req = {"identity": {"name": "Rare Name"}, "purpose": "research", "acknowledged": True}
    inv_id = client.post("/api/searches", json=req, headers=analyst_h).json()["id"]
    res = client.get(f"/api/searches/{inv_id}", headers=analyst_h).json()["result"]
    agents = [t["agent"] for t in res["agent_trace"]]
    assert agents == ["search", "evidence", "search", "evidence", "matching", "report"]
    assert '"Rare Name" linkedin' in res["queries"]


def test_calibration_is_monotone():
    scores = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95] * 3
    labels = [0, 0, 0, 1, 0, 1, 1, 1, 1, 1] * 3
    for method in ("platt", "isotonic"):
        cal = Calibrator.fit(scores, labels, method)
        preds = [cal.predict(s) for s in range(0, 101, 5)]
        assert preds == sorted(preds), method
        assert 0 <= preds[0] < 0.5 < preds[-1] <= 1
    try:
        Calibrator.fit([10, 90], [1, 1])
        assert False, "one-class labels must be rejected"
    except ValueError:
        pass


def test_evaluation_on_sample_dataset():
    rows = metrics.score_dataset(metrics.load_dataset(SAMPLE))
    m = metrics.metrics(rows, threshold=75)
    assert m["candidates"] == len(rows) and m["tp"] + m["fp"] + m["fn"] + m["tn"] == len(rows)
    assert m["precision"] == 1.0 and m["false_match_rate"] == 0.0
    assert m["top1_accuracy"] == 1.0
    w = metrics.suggest_weights(rows)
    assert w["company"]["suggested"] > 0 and set(w) == {"name", "company", "college", "role", "username", "location"}


def test_admin_evaluation_and_calibration(client, admin_h, analyst_h):
    req = {"identity": {"name": "Amir Choudhary", "company": "WASP3D"}, "purpose": "research", "acknowledged": True}
    inv_id = client.post("/api/searches", json=req, headers=analyst_h).json()["id"]
    cands = client.get(f"/api/searches/{inv_id}", headers=analyst_h).json()["result"]["candidates"]
    for c in cands:
        verdict = "correct" if c["candidate_id"] == "C001" else "wrong"
        client.post(f"/api/searches/{inv_id}/candidates/{c['candidate_id']}/feedback",
                    json={"verdict": verdict}, headers=analyst_h)
    ds = client.get("/api/admin/eval-dataset", headers=admin_h).json()
    assert any(case["id"] == inv_id for case in ds["cases"])
    ev = client.get("/api/admin/evaluation", headers=admin_h).json()
    assert ev["labels"] >= 3 and ev["rules_only"]["precision"] is not None
    cal = client.post("/api/admin/calibrate", json={"method": "platt"}, headers=admin_h).json()
    assert cal["active"] is False and "labels" in cal["message"]  # too few labels to be used

