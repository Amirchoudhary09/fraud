import os

import pytest

from app.core import config
from app.services import graph_export

REQ = {"identity": {"name": "Amir Choudhary", "company": "WASP3D", "college": "GLBITM"}, "purpose": "research",
       "acknowledged": True}
EVIL = "x'}) DETACH DELETE n //"


def test_cypher_escapes_hostile_values():
    graph = {"nodes": [{"id": "target", "type": "Target", "label": EVIL},
                       {"id": "cand:C1", "type": "Candidate", "label": "a\\'b\nc", "score": 90}],
             "edges": [{"source": "cand:C1", "target": "target", "type": "CITED_BY",
                        "sources": [{"url": "https://e.test/'); MATCH (n) DELETE n; //", "title": ""}]}]}
    script = graph_export.to_cypher("SRCH-1", graph)
    assert "n.label = 'x\\'}) DETACH DELETE n //'" in script  # stays inside a string literal
    assert "'a\\\\\\'b\\nc'" in script
    for line in script.splitlines()[2:]:
        assert line.startswith(("MERGE (n:EvidenceNode:", "MATCH (a:EvidenceNode"))


def test_unknown_labels_are_refused():
    with pytest.raises(ValueError):
        graph_export.to_cypher("S", {"nodes": [{"id": "x", "type": "Candidate`) DELETE n //", "label": "x"}], "edges": []})


def test_cypher_download_endpoint(client, admin_h, analyst_h):
    sid = client.post("/api/searches", json=REQ, headers=admin_h).json()["id"]
    r = client.get(f"/api/searches/{sid}/graph.cypher", headers=admin_h)
    assert r.status_code == 200 and "CREATE CONSTRAINT" in r.text and ":Candidate" in r.text and "WORKS_AT" in r.text
    assert client.post(f"/api/searches/{sid}/graph/neo4j", headers=admin_h).status_code == 404  # not configured


class _FakeSession:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.log.append((query, params))


class _FakeDriver:
    def __init__(self):
        self.log = []

    def session(self, database=None):
        return _FakeSession(self.log)


def test_push_uses_parameters_not_string_building():
    graph = {"nodes": [{"id": "target", "type": "Target", "label": EVIL}], "edges": []}
    d = _FakeDriver()
    assert graph_export.push("SRCH-9", graph, driver=d) == {"nodes": 1, "edges": 0}
    merge_q, params = d.log[1]
    assert EVIL not in merge_q and params["rows"][0]["label"] == EVIL


@pytest.mark.skipif(not os.getenv("TEST_NEO4J_URI"), reason="needs Neo4j (CI)")
def test_push_to_real_neo4j(client, admin_h, monkeypatch):
    from neo4j import GraphDatabase
    monkeypatch.setattr(config, "NEO4J_URI", os.environ["TEST_NEO4J_URI"])
    monkeypatch.setattr(config, "NEO4J_PASSWORD", os.environ["TEST_NEO4J_PASSWORD"])
    sid = client.post("/api/searches", json=REQ, headers=admin_h).json()["id"]
    out = client.post(f"/api/searches/{sid}/graph/neo4j", headers=admin_h).json()
    client.post(f"/api/searches/{sid}/graph/neo4j", headers=admin_h)  # idempotent
    with GraphDatabase.driver(config.NEO4J_URI, auth=("neo4j", config.NEO4J_PASSWORD)) as d, d.session() as s:
        nodes = s.run("MATCH (n:EvidenceNode {search_id: $s}) RETURN count(n) AS c", s=sid).single()["c"]
        rels = s.run("MATCH (a:EvidenceNode {search_id: $s})-[r]->() RETURN count(r) AS c", s=sid).single()["c"]
    assert nodes == out["nodes"] and rels == out["edges"]
