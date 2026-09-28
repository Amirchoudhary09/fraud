"""Evidence graph -> Neo4j.

to_cypher(): a self-contained Cypher script (for `cypher-shell` / Neo4j Browser). Every value is
    emitted as an escaped string literal, and labels / relationship types come from a fixed
    allowlist, so data from the public web can never become Cypher syntax.
push(): writes the graph into a live Neo4j (NEO4J_URI) with parameterised UNWIND queries.
Nodes are keyed by (search_id, id), so re-pushing is idempotent (MERGE).
"""
import re

from ..core import config
from .graph import NODE_TYPE, RELATION

LABELS = {"Target", "Candidate", "Source", "Profile", *NODE_TYPE.values()}
REL_TYPES = {"CITED_BY", "HAS_PROFILE", "OWNS_WEBSITE", "LINKS_TO", *RELATION.values(),
             *(f"INPUT_{r}" for r in RELATION.values())}
_SAFE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _lit(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    return f"'{s}'"


def _ident(name: str, allowed: set[str]) -> str:
    if name not in allowed or not _SAFE_IDENT.match(name):
        raise ValueError(f"Unexpected graph label/type: {name!r}")
    return name


def _props(search_id: str, n: dict) -> dict:
    return {"key": f"{search_id}:{n['id']}", "search_id": search_id, "node_id": n["id"], "label": n["label"],
            **{k: n[k] for k in ("score", "band", "url", "candidate_id") if n.get(k) is not None}}


def to_cypher(search_id: str, graph: dict) -> str:
    lines = [f"// Evidence graph for search {search_id}. Values are public evidence, not verified facts.",
             "CREATE CONSTRAINT evidence_node_key IF NOT EXISTS FOR (n:EvidenceNode) REQUIRE n.key IS UNIQUE;"]
    for n in graph["nodes"]:
        label = _ident(n["type"], LABELS)
        props = ", ".join(f"n.{k} = {_lit(v)}" for k, v in _props(search_id, n).items() if k != "key")
        lines.append(f"MERGE (n:EvidenceNode:{label} {{key: {_lit(f'{search_id}:' + n['id'])}}}) SET {props};")
    for e in graph["edges"]:
        rel = _ident(e["type"], REL_TYPES)
        urls = "[" + ", ".join(_lit(s["url"]) for s in e["sources"]) + "]"
        lines.append(f"MATCH (a:EvidenceNode {{key: {_lit(f'{search_id}:' + e['source'])}}}), "
                     f"(b:EvidenceNode {{key: {_lit(f'{search_id}:' + e['target'])}}}) "
                     f"MERGE (a)-[r:{rel}]->(b) SET r.sources = {urls};")
    return "\n".join(lines) + "\n"


def enabled() -> bool:
    return bool(config.NEO4J_URI)


def push(search_id: str, graph: dict, driver=None) -> dict:
    from neo4j import GraphDatabase
    own = driver is None
    driver = driver or GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
    try:
        with driver.session(database=config.NEO4J_DATABASE or None) as s:
            s.run("CREATE CONSTRAINT evidence_node_key IF NOT EXISTS FOR (n:EvidenceNode) REQUIRE n.key IS UNIQUE")
            by_label: dict[str, list] = {}
            for n in graph["nodes"]:
                by_label.setdefault(_ident(n["type"], LABELS), []).append(_props(search_id, n))
            for label, rows in by_label.items():  # labels cannot be parameters; they come from the allowlist
                s.run(f"UNWIND $rows AS row MERGE (n:EvidenceNode:{label} {{key: row.key}}) SET n += row", rows=rows)
            by_rel: dict[str, list] = {}
            for e in graph["edges"]:
                by_rel.setdefault(_ident(e["type"], REL_TYPES), []).append(
                    {"a": f"{search_id}:{e['source']}", "b": f"{search_id}:{e['target']}",
                     "sources": [x["url"] for x in e["sources"]]})
            for rel, rows in by_rel.items():
                s.run(f"UNWIND $rows AS row MATCH (a:EvidenceNode {{key: row.a}}), (b:EvidenceNode {{key: row.b}}) "
                      f"MERGE (a)-[r:{rel}]->(b) SET r.sources = row.sources", rows=rows)
    finally:
        if own:
            driver.close()
    return {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])}
