from app.schemas.identity import IdentityInput
from app.services.planner import broaden_queries, plan_queries


def test_initial_queries_cover_multiple_public_source_types():
    identity = IdentityInput(name="Amir Choudhary", company="WASP3D", college="GLBITM", username="amir09")
    queries = plan_queries(identity, max_queries=4)
    assert len(queries) == 4
    assert len(queries) == len(set(queries))
    assert any("amir09" in q for q in queries)
    assert any("WASP3D" in q for q in queries)
    assert any("linkedin.com" in q for q in queries)
    assert any("instagram.com" in q for q in queries)


def test_second_round_has_broad_domain_diversity():
    queries = broaden_queries(IdentityInput(name="Amir Choudhary", username="amir09"))
    joined = " ".join(queries)
    for domain in ("linkedin.com", "instagram.com", "youtube.com", "reddit.com", "personal website"):
        assert domain in joined
    assert len(queries) == len(set(queries))


def test_query_planner_handles_missing_optional_hints():
    queries = plan_queries(IdentityInput(name="A Person"), max_queries=3)
    assert len(queries) == 3
    assert all('"A Person"' in q for q in queries)
