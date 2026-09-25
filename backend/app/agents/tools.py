"""Least-privilege toolboxes for agents (spec section 23).

Each agent receives a Toolbox holding only the capabilities it was granted; calling anything
else raises AgentPermissionError. Routing between agents is deterministic (supervisor.route),
so text from web pages can never choose which tool runs next.

  search   : web search, query expansion, progress updates, audit events
  evidence : candidate extraction, progress updates, audit events
  matching : embeddings, LLM review, read calibration, progress updates
  report   : store the result, index evidence for Q&A, embeddings, audit events
No agent can delete data, change users/permissions, or touch the audit log except by appending.
"""
from ..core import config
from ..core.database import now
from ..repositories import searches
from ..services import audit, calibration, rag

GRANTS = {
    "search": {"web.search", "web.expand_queries", "progress", "audit.append"},
    "evidence": {"llm.extract", "progress", "audit.append"},
    "matching": {"llm.embed", "llm.judge", "calibration.read", "progress"},
    "report": {"result.store", "rag.index", "llm.embed", "audit.append"},
}


class AgentPermissionError(PermissionError):
    pass


class Toolbox:
    def __init__(self, agent: str, provider, search_id: str):
        self.agent, self._p, self.search_id = agent, provider, search_id
        self._grants = GRANTS[agent]

    def _need(self, cap: str):
        if cap not in self._grants:
            raise AgentPermissionError(f"agent '{self.agent}' is not allowed to use '{cap}'")

    @property
    def provider_name(self) -> str:
        return self._p.name

    # web / llm
    def search(self, query: str):
        self._need("web.search")
        return self._p.search(query)

    def expand_queries(self, identity, tried):
        self._need("web.expand_queries")
        return self._p.expand_queries(identity, tried)

    def extract(self, identity, results):
        self._need("llm.extract")
        return self._p.extract_candidates(identity, results)

    def matcher(self):
        """The provider facade handed to matching: only embed + judge + embed_range."""
        self._need("llm.embed")
        self._need("llm.judge")
        p = self._p

        class _Matcher:
            name = p.name
            embed_range = p.embed_range
            embed = staticmethod(p.embed)
            judge = staticmethod(p.judge)
        return _Matcher()

    def calibrator(self):
        self._need("calibration.read")
        return calibration.load(config.CALIBRATION_PATH, config.MIN_CALIBRATION_LABELS)

    # state
    def progress(self, stage: str):
        self._need("progress")
        searches.update(self.search_id, status="running", stage=stage)

    def audit(self, event_type: str, **kw):
        self._need("audit.append")
        audit.record(event_type, target_type="SEARCH", target_id=self.search_id, search_id=self.search_id, **kw)

    def store_result(self, result: dict, candidate_count: int, sources_used: list[str]):
        self._need("result.store")
        searches.update(self.search_id, status="completed", stage="Complete", result=result,
                        candidate_count=candidate_count, sources_used=sources_used, completed_at=now())

    def index_evidence(self, result: dict) -> int:
        self._need("rag.index")
        self._need("llm.embed")
        return rag.index(self.search_id, result, self._p)
