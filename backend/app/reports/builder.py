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
