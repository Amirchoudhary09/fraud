"""Evidence graph: people, organisations, places and sources as nodes; cited claims as edges.

Built on demand from a finished investigation, so no graph database is needed yet. The
{nodes, edges} shape maps 1:1 onto Neo4j (node label = type, edge type = relation) if one
is added later.
"""
from urllib.parse import urlparse

from .similarity import MATCH_AT, similarity

RELATION = {"company": "WORKS_AT", "college": "STUDIED_AT", "location": "LOCATED_IN",
            "role": "HAS_ROLE", "username": "HAS_USERNAME"}
NODE_TYPE = {"company": "Company", "college": "College", "location": "Place", "role": "Role",
             "username": "Username"}


def build(inv: dict) -> dict:
    nodes: dict[str, dict] = {}
    edges: dict[tuple, dict] = {}
    values: dict[str, list[tuple[str, str]]] = {f: [] for f in RELATION}  # field -> [(node_id, value)]

    def node(nid: str, ntype: str, label: str, **extra) -> str:
        nodes.setdefault(nid, {"id": nid, "type": ntype, "label": label[:80], **extra})
        return nid

    def attr(field: str, value: str) -> str:
        # Merge equivalent values ("GLBITM" ~ "G L Bajaj Institute ...") into one node.
        for nid, v in values[field]:
            if similarity(field, v, value) >= MATCH_AT:
                return nid
        nid = f"{field}:{len(values[field]) + 1}"
        values[field].append((nid, value))
        return node(nid, NODE_TYPE[field], value)

    def edge(src: str, dst: str, rel: str, source: dict | None = None):
        e = edges.setdefault((src, dst, rel), {"source": src, "target": dst, "type": rel, "sources": []})
        if source and source["url"] not in {s["url"] for s in e["sources"]}:
            e["sources"].append(source)

    target = node("target", "Target", inv["input"].get("name", "Target"))
    for field in RELATION:
        if inv["input"].get(field):
            edge(target, attr(field, inv["input"][field]), "INPUT_" + RELATION[field])

    for c in (inv.get("result") or {}).get("candidates", []):
        pid = node(f"cand:{c['candidate_id']}", "Candidate", c["display_name"],
                   score=c["score"], band=c["band"], candidate_id=c["candidate_id"])
        for cl in c["claims"]:
            src = cl.get("source")
            if src:
                domain = src.get("title") or urlparse(src["url"]).netloc
                sid = node(f"src:{src['url']}", "Source", domain, url=src["url"])
                edge(pid, sid, "CITED_BY", src)
            if cl["field"] in RELATION:
                edge(pid, attr(cl["field"], cl["value"]), RELATION[cl["field"]], src)
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}
