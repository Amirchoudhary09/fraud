"""Worker agents. Each gets the shared state plus its own least-privilege Toolbox, and returns
only the keys it changed."""
import logging
from urllib.parse import urlparse

from ..core import config
from ..core.database import now
from ..services.matching import rank
from ..services.planner import broaden_queries, plan_queries
from .state import InvestigationState
from .tools import Toolbox

log = logging.getLogger(__name__)
MAX_SEARCH_ROUNDS = 2


def _trace(state: InvestigationState, agent: str, detail: str) -> list[dict]:
    return state.get("trace", []) + [{"agent": agent, "detail": detail, "ts": now()}]


def search_agent(state: InvestigationState, tools: Toolbox) -> dict:
    identity, rounds = state["identity"], state.get("search_rounds", 0)
    tried = state.get("queries", [])
    if rounds == 0:
        queries = plan_queries(identity, config.MAX_QUERIES)
        why = "initial search plan"
    else:
        try:
            queries = tools.expand_queries(identity, tried)
        except Exception as e:
            log.warning("query expansion failed: %s", e)
            queries = []
        queries = [q for q in queries + broaden_queries(identity) if q not in tried][:config.MAX_QUERIES]
        why = "no candidates found, broadening search"

    results, errors = list(state.get("results", [])), list(state.get("errors", []))
    for i, q in enumerate(queries, 1):
        tools.progress(f"Search agent: {why} ({i}/{len(queries)})")
        tools.audit("SEARCH_QUERY_CREATED", detail={"round": rounds + 1, "n": i})
        try:
            r = tools.search(q)
            results.append(r)
            tools.audit("SEARCH_EXECUTED", detail={"round": rounds + 1, "n": i, "sources": len(r.sources)})
        except Exception as e:  # one failed query shouldn't sink the investigation
            log.warning("search failed for %r: %s", q, e)
            errors.append(f"{q}: {e}")
            tools.audit("SEARCH_EXECUTED", result="FAILED", detail={"round": rounds + 1, "n": i, "error": str(e)[:200]})
    if not results:
        raise RuntimeError("All searches failed. " + " | ".join(errors))
    tools.audit("SEARCH_RESULTS_RECEIVED", detail={"results": len(results), "failed": len(errors)})
    return {"queries": tried + queries, "results": results, "errors": errors, "search_rounds": rounds + 1,
            "candidates": None, "trace": _trace(state, "search", f"{why}: {len(queries)} queries")}


def evidence_agent(state: InvestigationState, tools: Toolbox) -> dict:
    tools.progress("Evidence agent: extracting candidates and cited claims")
    cands = tools.extract(state["identity"], state["results"])
    for c in cands:
        tools.audit("CANDIDATE_CREATED", detail={"candidate_id": c.candidate_id, "claims": len(c.claims)})
    claims = sum(len(c.claims) for c in cands)
    return {"candidates": cands, "trace": _trace(state, "evidence", f"{len(cands)} candidates, {claims} cited claims")}


def matching_agent(state: InvestigationState, tools: Toolbox) -> dict:
    tools.progress("Matching agent: rules + embeddings + LLM review, contradictions")
    scored = rank(state["identity"], state["candidates"], tools.matcher(), tools.calibrator(),
                  use_judge=config.LLM_JUDGE, max_judged=config.MAX_JUDGED_CANDIDATES)
    top = f"top score {scored[0].score}" if scored else "no candidates"
    return {"scored": scored, "trace": _trace(state, "matching", f"{len(scored)} scored, {top}")}


def report_agent(state: InvestigationState, tools: Toolbox) -> dict:
    results = state["results"]
    trace = _trace(state, "report", "results stored, evidence indexed for Q&A")
    all_sources = {s.url: s.model_dump() for r in results for s in r.sources}
    result = {
        "queries": state["queries"],
        "search_errors": state.get("errors", []),
        "summaries": [{"query": r.query, "summary": r.summary} for r in results],
        "sources": list(all_sources.values()),
        "candidates": [c.model_dump() for c in state["scored"]],
        "mock": tools.provider_name == "mock",
        "agent_trace": trace,
    }
    try:
        result["indexed_chunks"] = tools.index_evidence(result)
    except Exception as e:  # Q&A is optional; the search itself succeeded
        log.warning("RAG indexing failed for %s: %s", tools.search_id, e)
        result["indexed_chunks"] = 0
    domains = sorted({(s.get("title") or urlparse(s["url"]).netloc) for s in all_sources.values()})
    tools.store_result(result, len(state["scored"]), [tools.provider_name] + domains[:50])
    tools.audit("SEARCH_COMPLETED", detail={"candidates": len(state["scored"]), "sources": len(all_sources)})
    return {"reported": True, "trace": trace}
