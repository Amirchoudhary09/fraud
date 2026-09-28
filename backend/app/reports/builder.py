"""Builds report documents as plain data; html.py and pdf.py render the same document.

Document = {"title", "notice", "warning", "sections": [{"title", "blocks": [block]}]}
block    = {"p": str} | {"list": [str | {"text", "links": [{"url", "label"}]}]}
         | {"table": {"headers": [str], "rows": [[str]]}}
"""
from ..core.database import now

NOTICE = ("This report lists publicly available information, content indicators and a heuristic evidence "
          "score. It is not proof of identity and not a legal or criminal finding. Every match and every "
          "indicator requires human review.")
MOCK_WARNING = "DEMO DATA: generated in mock mode, not real search results."


def _link(s: dict) -> dict:
    return {"url": s["url"], "label": s.get("title") or s["url"]}


def _confidence(c: dict) -> str:
    txt = f"Evidence score {c['score']}/100 ({c['band']})"
    if c.get("calibrated") is not None:
        txt += f"; calibrated match probability {round(c['calibrated'] * 100)}%"
    return txt


def candidate_blocks(c: dict, verdict: str | None) -> list[dict]:
    return [
        {"p": f"{_confidence(c)}. Reviewer verdict: {verdict or 'not reviewed'}."},
        {"p": "Matching analysis (why this score):"},
        {"list": [{"text": f"{s['field']} [{s['status']}, {s['points']:+d}] {s['detail']}",
                   "links": [_link(x) for x in s["sources"]]} for s in c["signals"]]},
        {"p": "Contradictions:"},
        {"list": [{"text": x["detail"], "links": [_link(s) for s in x["sources"]]} for x in c["contradictions"]]
         or ["None found"]},
        {"p": "Evidence collected:"},
        {"table": {"headers": ["Field", "Value", "Evidence", "Source"],
                   "rows": [[cl["field"], cl["value"], cl.get("evidence", ""), (cl["source"] or {}).get("url", "")]
                            for cl in c["claims"] if cl.get("source")]}},
    ]


def search_blocks(s: dict, feedback: dict, top: int | None = None) -> list[dict]:
    res = s["result"]
    blocks = [{"p": f"Search {s['id']} by user #{s['user_id']} ({s['search_type']}), started {s['created_at']}, "
                    f"completed {s.get('completed_at') or '-'}. Input: "
                    + ", ".join(f"{k}={v}" for k, v in s["input"].items())},
              {"p": "Queries: " + "; ".join(res["queries"])}]
    for c in res["candidates"][:top]:
        blocks.append({"p": f"Possible public profile {c['candidate_id']}: {c['display_name']} ({c['platform']})"})
        blocks += candidate_blocks(c, feedback.get(c["candidate_id"]))
    blocks.append({"p": "Source URLs:"})
    blocks.append({"list": [{"text": x.get("title") or x["url"], "links": [_link(x)]} for x in res["sources"]]
                   or ["None"]})
    return blocks


def search_report(s: dict, feedback: dict) -> dict:
    sections = [
        {"title": "1. Search record", "blocks": [{"table": {"headers": ["", ""], "rows": [
            ["Search ID", s["id"]], ["Type", s["search_type"]], ["Started (UTC)", s["created_at"]],
            ["Completed (UTC)", s.get("completed_at") or ""], ["Purpose", s["purpose"]], ["Provider", s["provider"]],
            ["Case", s.get("case_id") or "-"], ["Report generated (UTC)", now()]]}}]},
        {"title": "2. Input identity", "blocks": [{"table": {"headers": ["Field", "Value"],
                                                             "rows": [[k, str(v)] for k, v in s["input"].items()]}}]},
        {"title": "3. Candidates, evidence, matching, contradictions, confidence", "blocks": search_blocks(s, feedback)},
    ]
    fp = s["result"].get("footprint")
    if fp:
        sections = footprint_sections(fp) + sections
    return {"title": f"Public Evidence Report {s['id']}", "notice": NOTICE,
            "warning": MOCK_WARNING if s["result"].get("mock") else None, "sections": sections}


def case_report(case: dict, incidents: list[dict], evidence: list[dict], analyses: list[dict], searches: list[dict],
                feedback: dict[str, dict], timeline: list[dict], texts: dict[str, str]) -> dict:
    by_evidence = {a["evidence_id"]: a for a in analyses}
    mock = any((s.get("result") or {}).get("mock") for s in searches)
    sections = [
        {"title": "1. Incident information", "blocks": [
            {"table": {"headers": ["", ""], "rows": [
                ["Case ID", case["id"]], ["Title", case["title"]], ["Status", case["status"]],
                ["Purpose", case["purpose"]], ["Created by", case.get("created_by_email") or str(case["created_by"])],
                ["Target entity", case.get("target_entity") or "-"], ["Opened (UTC)", case["created_at"]],
                ["Report generated (UTC)", now()]]}},
            {"p": case.get("description") or "No description."},
            {"table": {"headers": ["Incident", "Type", "Severity", "Status", "Target", "Reported (UTC)"],
                       "rows": [[i["id"], i["incident_type"], i["severity"], i["status"], i.get("target_entity") or "",
                                 i["created_at"]] for i in incidents]}}]},
        {"title": "2. Original content", "blocks": [{"list": [
            f"[{e['id']}] \"{texts[e['id']]}\"" for e in evidence if e["id"] in texts and e["type"] == "PUBLIC_COMMENT"]
            or ["No comment text recorded."]}]},
        {"title": "3. Source", "blocks": [{"table": {
            "headers": ["Incident", "Platform", "Public handle", "Content ID", "URL"],
            "rows": [[i["id"], i.get("source_platform") or "", i.get("author_handle") or "", i.get("content_id") or "",
                      i.get("source_url") or ""] for i in incidents]}}]},
        {"title": "4. Evidence collected (integrity hashes)", "blocks": [{"table": {
            "headers": ["Evidence", "Type", "Captured (UTC)", "Method", "Source", "SHA-256"],
            "rows": [[e["id"], e["type"], e["captured_at"], e["capture_method"], e.get("source_url") or "",
                      e["content_hash"]] for e in evidence]}}]},
        {"title": "5. AI content analysis (indicators, not findings)", "blocks": [{"table": {
            "headers": ["Evidence", "Severity", "Indicators", "Matched phrases", "Model"],
            "rows": [[eid, a["result"]["severity"],
                      ", ".join(k.removesuffix("_indicator") for k, v in a["result"]["indicators"].items() if v) or "none",
                      "; ".join(f"{k}: {', '.join(v)}" for k, v in a["result"]["rule_matches"].items()), a["model"]]
                     for eid, a in by_evidence.items() if a.get("result") and "indicators" in a["result"]]}}]},
    ]
    n = 6
    for s in searches:
        if s["status"] == "completed":
            sections.append({"title": f"{n}. Public profile information, matching, contradictions, confidence",
                             "blocks": search_blocks(s, feedback.get(s["id"], {}), top=3)})
            n += 1
    sections.append({"title": f"{n}. Evidence timeline", "blocks": [{"table": {
        "headers": ["Time (UTC)", "Event", "By", "Target"],
        "rows": [[t["ts"], t["event_type"], t["actor"], f"{t['target_type'] or ''} {t['target_id'] or ''}".strip()]
                 for t in timeline]}}]})
    return {"title": f"Case Report {case['id']}: {case['title']}", "notice": NOTICE,
            "warning": MOCK_WARNING if mock else None, "sections": sections}


def _acct(a: dict) -> str:
    return f"{a['platform']}: {a.get('username') or a.get('profile_url') or '?'}"


def footprint_sections(fp: dict) -> list[dict]:
    """Report sections for a public-footprint search (executive summary through human review)."""
    accounts = fp.get("accounts", [])
    target = set(fp.get("target_candidates", []))
    mine = [a for a in accounts if a["candidate_id"] in target]
    found = [a for a in mine if a["status"] == "FOUND"]
    possible = [a for a in mine if a["status"] == "POSSIBLE MATCH"]
    status_rows = fp.get("platform_status", [])
    count = lambda st: sum(1 for r in status_rows if r["status"] == st)  # noqa: E731
    exp = fp.get("expansion", {})

    def account_table(rows):
        return {"table": {"headers": ["Candidate", "Account", "Status", "Score", "Found via", "URL"],
                          "rows": [[a["candidate_id"], _acct(a), a["status"], str(a["score"]), a.get("discovered_via", ""),
                                    a.get("profile_url") or ""] for a in rows]}}

    def why(rows):
        items = []
        for a in rows:
            e = a["explanation"]
            items.append({"text": f"{_acct(a)} ({a['score']}): why it matches: {'; '.join(e['why_match']) or 'nothing'}. "
                                  f"Why it may not: {'; '.join(e['why_it_may_not_match']) or 'nothing noted'}.",
                          "links": [{"url": u, "label": u} for u in e["supporting_sources"] + e["contradicting_sources"]]})
        return {"list": items or ["None"]}

    sources = sorted({a["source"]["url"] for a in accounts if a.get("source")} |
                     {e["source"]["url"] for e in fp.get("timeline", []) if e.get("source")})
    links = [f"{_acct(a)} is linked from {a['linked_from']}" for a in accounts if a.get("linked_from")]
    return [
        {"title": "Executive summary", "blocks": [{"p": (
            f"{len(found)} high-confidence and {len(possible)} possible public profiles for the target candidate "
            f"({', '.join(sorted(target)) or 'none identified'}); {len(accounts)} accounts examined across "
            f"{len({a['candidate_id'] for a in accounts})} candidate(s). Platforms: {count('FOUND')} found, "
            f"{count('POSSIBLE MATCH')} possible, {count('INSUFFICIENT EVIDENCE')} insufficient evidence, "
            f"{count('NOT FOUND')} not found, {count('NOT SEARCHABLE')} not searchable. Link expansion: "
            f"{exp.get('rounds', 0)} round(s), {exp.get('leads_followed', 0)} lead(s), "
            f"{exp.get('pages_fetched', 0)} public page(s) read; stopped because {exp.get('stopped_because', '-')}.")}]},
        {"title": "Discovered public profiles", "blocks": [account_table(accounts)]},
        {"title": "High-confidence profiles", "blocks": [why(found)]},
        {"title": "Possible profiles", "blocks": [why(possible)]},
        {"title": "Platform-by-platform results", "blocks": [{"table": {
            "headers": ["Platform", "Status", "Detail"], "rows": [[r["name"], r["status"], r["detail"]] for r in status_rows]}}]},
        {"title": "Cross-platform connections", "blocks": [{"list": links or ["No published cross-links found."]}]},
        {"title": "Public account history", "blocks": [{"list": [
            f"{_acct(a)}: " + "; ".join(f"{e['date']} {e['event']}" for e in a.get("events", []))
            for a in found if a.get("events")] or ["No dated public history found for high-confidence accounts."]}]},
        {"title": "Chronological timeline", "blocks": [{"table": {
            "headers": ["Date", "Platform", "Event", "Source", "Confidence"],
            "rows": [[e["date"], e["platform"], e["event"], (e.get("source") or {}).get("url", ""), e["confidence"]]
                     for e in fp.get("timeline", [])]}}]},
        {"title": "Evidence graph", "blocks": [{"p": "Candidate -HAS_PROFILE/OWNS_WEBSITE-> profile and profile "
                                                     "-LINKS_TO-> profile edges, each with its source; see the graph view "
                                                     "or the Cypher export for the full graph."}]},
        {"title": "Contradictions", "blocks": [{"list": [f"{_acct(a)} [{a['candidate_id']}]: {c}"
                                                          for a in accounts for c in a.get("contradictions", [])]
                                                         or ["None found."]}]},
        {"title": "Sources", "blocks": [{"list": [{"text": u, "links": [{"url": u, "label": u}]} for u in sources] or ["None"]}]},
        {"title": "Limitations", "blocks": [{"list": [
            "Only publicly indexed information was used; login-walled networks are marked NOT SEARCHABLE and were not accessed.",
            "Social networks were never fetched directly; their evidence comes from search results and links the person published.",
            "NOT FOUND means no reliable public result within the query budget, not that no account exists.",
            "Scores are heuristic evidence scores, not probabilities. A username match alone is never treated as a match.",
            "Historical data is limited to publicly documented dates and Internet Archive captures of personal websites."]}]},
        {"title": "Human review required", "blocks": [{"p": (
            "Every profile must be reviewed by a person before any action. Do not contact, expose or report anyone "
            "based on this report alone; verify each cited source first.")}]},
    ]
