"""Worker agents. Each gets the shared state plus its own least-privilege Toolbox, and returns
only the keys it changed."""
import logging
from urllib.parse import urlparse

from ..core import config
from ..core.database import now
from ..services.matching import rank
from ..services import footprint, platforms
from ..services.planner import broaden_queries, footprint_queries, plan_queries
from ..schemas.identity import Profile, TimelineEvent, SourceRef
from .state import InvestigationState
from .tools import Toolbox

log = logging.getLogger(__name__)
MAX_SEARCH_ROUNDS = 2


def _trace(state: InvestigationState, agent: str, detail: str) -> list[dict]:
    return state.get("trace", []) + [{"agent": agent, "detail": detail, "ts": now()}]


def search_agent(state: InvestigationState, tools: Toolbox) -> dict:
    identity, rounds = state["identity"], state.get("search_rounds", 0)
    tried = state.get("queries", [])
    searched = set(state.get("searched_platforms", []))
    if rounds == 0 and state.get("mode") == "footprint":
        fp = footprint_queries(identity, config.FOOTPRINT_MAX_QUERIES)
        queries = plan_queries(identity, 2) + [q for q, _ in fp]
        searched |= {k for _, keys in fp for k in keys}
        why = "public footprint plan"
    elif rounds == 0:
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
            "candidates": None, "searched_platforms": sorted(searched),
            "trace": _trace(state, "search", f"{why}: {len(queries)} queries")}


def evidence_agent(state: InvestigationState, tools: Toolbox) -> dict:
    tools.progress("Evidence agent: extracting candidates and cited claims")
    cands = tools.extract(state["identity"], state["results"], with_profiles=state.get("mode") == "footprint")
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


def _score_all(identity, cands) -> list[dict]:
    accounts = []
    for c in cands:
        for a in footprint.score_candidate_accounts(identity, c.profiles):
            accounts.append({**a, "candidate_id": c.candidate_id})
    return accounts


def expansion_agent(state: InvestigationState, tools: Toolbox) -> dict:
    """Public-footprint graph expansion: accounts already FOUND publish links to other accounts and
    sites; each unseen link becomes a lead. Personal sites / link-in-bio pages are fetched (SSRF-safe,
    budgeted) to find further links; social networks are never fetched, their link itself is the
    evidence. Stops when no new leads appear or a budget (rounds, fetches, leads) runs out."""
    identity, cands = state["identity"], state["scored"]
    by_id = {c.candidate_id: c for c in cands}
    for c in cands:
        c.profiles.extend(footprint.profiles_from_claims(c))
    fetches, followed, rounds_run, stop = 0, 0, 0, "no new public leads"
    fetched: set[str] = set()

    def read_page(prof: Profile) -> None:
        """Fetches a public personal/link-in-bio page once and records its outbound links."""
        nonlocal fetches
        url = prof.profile_url
        if not url or footprint.norm_url(url) in fetched or fetches >= config.FOOTPRINT_MAX_FETCHES \
                or not platforms.fetchable_url(url):
            return
        fetched.add(footprint.norm_url(url))
        fetches += 1
        page = tools.fetch_public_page(url)
        if page and page.get("body"):
            title, links = footprint.links_in_html(page["body"].decode("utf-8", "replace"), page["final_url"])
            prof.public_links = list(dict.fromkeys(prof.public_links + links))
            prof.public_bio = prof.public_bio or title[:600] or None

    for rnd in range(config.FOOTPRINT_MAX_ROUNDS):
        accounts = _score_all(identity, cands)
        # High-confidence websites / link-in-bio pages are read for further published links.
        for a in accounts:
            if a["status"] == "FOUND":
                prof = next((p for p in by_id[a["candidate_id"]].profiles
                             if footprint.norm_url(p.profile_url) == footprint.norm_url(a.get("profile_url"))), None)
                if prof:
                    read_page(prof)
        accounts = _score_all(identity, cands)
        known = {footprint.norm_url(a.get("profile_url")) for a in accounts}
        new = footprint.leads(accounts, known)
        if not new:
            break
        rounds_run += 1
        tools.progress(f"Expansion agent: round {rnd + 1}, {len(new)} new public lead(s)")
        for lead in new:
            if followed >= config.FOOTPRINT_MAX_LEADS:
                stop = "lead budget reached"
                break
            followed += 1
            key, user = platforms.classify_url(lead["url"])
            prof = Profile(platform=key, username=user, profile_url=lead["url"], linked_from=lead["from"],
                           discovered_via="cross_link", source=SourceRef(url=lead["from"] or lead["url"], title="cross-link"))
            by_id[lead["candidate_id"]].profiles.append(prof)
            tools.audit("FOOTPRINT_LEAD_FOLLOWED", detail={"platform": key})
        else:
            continue
        break
    else:
        stop = "round budget reached"

    accounts = _score_all(identity, cands)
    # Public history of HIGH-confidence personal websites: first Internet Archive capture.
    for a in accounts:
        if a["status"] == "FOUND" and a["platform"] == "website" and a.get("profile_url"):
            ts = tools.archive_first_capture(a["profile_url"])
            if ts:
                date = f"{ts[:4]}-{ts[4:6]}"
                a["events"].append(TimelineEvent(date=date, platform="website", event="Website first archived by the Internet Archive",
                                                 source=SourceRef(url=f"https://web.archive.org/web/{ts}/{a['profile_url']}",
                                                                  title="web.archive.org"), confidence="MEDIUM").model_dump())
    top = [c.candidate_id for c in cands if c.band in ("strong", "possible")][:1]
    result = {
        "accounts": accounts,
        "platform_status": footprint.platform_status(accounts, set(state.get("searched_platforms", [])), set(top)),
        "timeline": footprint.timeline([a for a in accounts if a["candidate_id"] in top]),
        "target_candidates": top,
        "expansion": {"rounds": rounds_run, "leads_followed": followed, "pages_fetched": fetches, "stopped_because": stop},
    }
    found = sum(1 for a in accounts if a["status"] == "FOUND" and a["candidate_id"] in top)
    tools.audit("FOOTPRINT_MAPPED", detail={"accounts": len(accounts), "found": found, **result["expansion"]})
    return {"footprint": result, "trace": _trace(state, "expansion",
            f"{len(accounts)} accounts ({found} high-confidence), {rounds_run} round(s), stopped: {stop}")}


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
        "mode": state.get("mode", "standard"),
        "footprint": state.get("footprint"),
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
