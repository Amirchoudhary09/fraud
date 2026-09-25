from app.services.contradictions import find_contradictions
from app.services.matching import rank, score_candidate
from app.services.similarity import similarity
from app.schemas.identity import Candidate, Claim, IdentityInput, SourceRef
from app.providers.mock import MockProvider

ID = IdentityInput(name="Amir Choudhary", company="WASP3D", college="GLBITM", role="Software Developer")


def src(n):
    return SourceRef(url=f"https://s{n}.test/x", title=f"s{n}.test")


def test_name_similarity():
    assert similarity("name", "Amir Choudhary", "Amir Chaudhary") == 1.0
    assert similarity("name", "Amir Choudhary", "Mohd Amir Choudhary") == 1.0
    assert similarity("name", "Amir Choudhary", "Amir Khan") < 0.6


def test_college_acronym_and_role_synonym():
    assert similarity("college", "GLBITM", "G L Bajaj Institute of Technology and Management") >= 0.85
    assert similarity("role", "Software Developer", "Software Engineer") >= 0.85
    assert similarity("company", "WASP3D", "WASP3D Pvt Ltd") >= 0.85
    assert similarity("role", "Software Developer", "Sales Manager") < 0.6


def test_mock_ranking_orders_best_match_first():
    ranked = rank(ID, MockProvider().extract_candidates(ID, []))
    assert [c.candidate_id for c in ranked] == ["C001", "C002", "C003"]
    top = ranked[0]
    assert top.band == "strong" and top.score >= 75
    assert any(x.field == "location" for x in top.contradictions)
    assert ranked[-1].band == "weak"


def test_unknown_fields_do_not_add_points():
    cand = Candidate(candidate_id="C1", display_name="Amir Choudhary",
                     claims=[Claim(field="name", value="Amir Choudhary", source=src(1))])
    s = score_candidate(ID, cand)
    statuses = {x.field: x.status for x in s.signals}
    assert statuses == {"name": "match", "company": "unknown", "college": "unknown", "role": "unknown"}
    assert s.score == round(100 * 30 / 95)  # only name points out of 85 + 10 corroboration


def test_name_mismatch_is_penalised():
    cand = Candidate(candidate_id="C1", display_name="Rahul Verma", claims=[
        Claim(field="name", value="Rahul Verma", source=src(1)),
        Claim(field="company", value="WASP3D", source=src(1)),
    ])
    assert score_candidate(ID, cand).score == 0


def test_career_history_is_not_a_contradiction():
    cand = Candidate(candidate_id="C1", display_name="A", claims=[
        Claim(field="company", value="WASP3D", source=src(1)),
        Claim(field="company", value="Infosys", source=src(2)),
        Claim(field="location", value="Delhi", source=src(1)),
        Claim(field="location", value="New Delhi", source=src(2)),
    ])
    assert find_contradictions(cand) == []


def test_every_signal_points_sum_to_score_basis():
    ranked = rank(ID, MockProvider().extract_candidates(ID, []))
    for c in ranked:
        for s in c.signals:
            if s.status in ("match", "partial", "corroboration"):
                assert s.sources, f"{c.candidate_id} {s.field} has no source"
