"""Investigation pipeline: plan -> search -> candidates -> match -> contradictions -> result."""
import logging

from . import config, db
from .matching import rank
from .models import IdentityInput
from .planner import plan_queries
from .providers.gemini import GeminiProvider
from .providers.mock import MockProvider

log = logging.getLogger(__name__)


def get_provider():
    if config.MOCK_MODE:
        return MockProvider()
    return GeminiProvider(config.GEMINI_API_KEY, config.GEMINI_MODEL)


def run_investigation(inv_id: str, identity: IdentityInput, provider=None) -> None:
    provider = provider or get_provider()
    try:
        db.update_investigation(inv_id, status="running", stage="Planning search queries")
        queries = plan_queries(identity, config.MAX_QUERIES)

        results, errors = [], []
        for i, q in enumerate(queries, 1):
            db.update_investigation(inv_id, stage=f"Searching public web ({i}/{len(queries)})")
            try:
                results.append(provider.search(q))
            except Exception as e:  # one failed query shouldn't sink the investigation
                log.warning("search failed for %r: %s", q, e)
                errors.append(f"{q}: {e}")
        if not results:
            raise RuntimeError("All searches failed. " + " | ".join(errors))

        db.update_investigation(inv_id, stage="Extracting candidates and evidence")
        candidates = provider.extract_candidates(identity, results)

        db.update_investigation(inv_id, stage="Matching and checking contradictions")
        scored = rank(identity, candidates)

        all_sources = {s.url: s.model_dump() for r in results for s in r.sources}
        db.update_investigation(inv_id, status="done", stage="Complete", result={
            "queries": queries,
            "search_errors": errors,
            "summaries": [{"query": r.query, "summary": r.summary} for r in results],
            "sources": list(all_sources.values()),
            "candidates": [c.model_dump() for c in scored],
            "mock": provider.name == "mock",
        })
        db.audit("investigation_done", inv_id, detail=f"{len(scored)} candidates")
    except Exception as e:
        log.exception("investigation %s failed", inv_id)
        db.update_investigation(inv_id, status="failed", stage="Failed", error=str(e)[:1000])
        db.audit("investigation_failed", inv_id, detail=str(e))
