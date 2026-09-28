"""Supervisor: a LangGraph state machine that routes between the worker agents.

    supervisor ─┬─> search   (no results yet, or no candidates and search rounds left)
                ├─> evidence (results not yet turned into candidates)
                ├─> matching (candidates not yet scored)
                ├─> expansion (footprint mode: follow published links, score every account)
                ├─> report   (scored, not yet stored)
                └─> END
Every worker returns to the supervisor, which re-reads the state and decides again.
Routing is plain code over the state, never an LLM decision, so retrieved web content
cannot steer which agent or tool runs.
"""
import logging
from functools import partial

from langgraph.graph import END, StateGraph

from ..core import context
from ..core.database import now
from ..providers import get_provider
from ..repositories import searches
from ..schemas.identity import IdentityInput
from ..services import audit
from . import nodes
from .state import InvestigationState
from .tools import Toolbox

log = logging.getLogger(__name__)


def route(state: InvestigationState) -> str:
    if not state.get("results"):
        return "search"
    if state.get("candidates") is None:
        return "evidence"
    if not state["candidates"] and state.get("search_rounds", 0) < nodes.MAX_SEARCH_ROUNDS:
        return "search"
    if state.get("scored") is None:
        return "matching"
    if state.get("mode") == "footprint" and state.get("footprint") is None:
        return "expansion"
    if not state.get("reported"):
        return "report"
    return END


def build_graph(provider, search_id: str):
    g = StateGraph(InvestigationState)
    g.add_node("supervisor", lambda state: {})
    for name, fn in (("search", nodes.search_agent), ("evidence", nodes.evidence_agent),
                     ("matching", nodes.matching_agent), ("expansion", nodes.expansion_agent),
                     ("report", nodes.report_agent)):
        g.add_node(name, partial(fn, tools=Toolbox(name, provider, search_id)))
        g.add_edge(name, "supervisor")
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", route,
                            {"search": "search", "evidence": "evidence", "matching": "matching",
                             "expansion": "expansion", "report": "report", END: END})
    return g.compile()


def run_investigation(search_id: str, identity: IdentityInput, user_id: int | None = None,
                      request_id: str | None = None, ip_hash: str | None = None, provider=None,
                      mode: str = "standard") -> None:
    # Runs on a worker thread: re-bind the originating request so audit events stay attributed.
    context.bind(request_id, user_id, ip_hash)
    provider = provider or get_provider()
    try:
        searches.update(search_id, status="running", stage="Supervisor: planning", started_at=now())
        build_graph(provider, search_id).invoke({"search_id": search_id, "identity": identity, "trace": [], "mode": mode},
                                                {"recursion_limit": 25})
    except Exception as e:
        log.exception("search %s failed", search_id)
        searches.update(search_id, status="failed", stage="Failed", error=str(e)[:1000], completed_at=now())
        audit.record("SEARCH_FAILED", target_type="SEARCH", target_id=search_id, search_id=search_id,
                     result="FAILED", detail=str(e)[:500])
