"""RAG over an investigation's collected public evidence ("ask the evidence").

RAG retrieves and summarises evidence that was already collected and cited. It does not
search again and it is not proof of identity: answers must cite the stored chunks.
"""
from ..core.privacy import find_blocked_terms
from ..repositories import vectors


def chunks_from_result(result: dict) -> list[dict]:
    out = []
    for c in result.get("candidates", []):
        for cl in c["claims"]:
            src = cl.get("source") or {}
            out.append({
                "candidate_id": c["candidate_id"],
                "text": f"{c['display_name']} ({c['candidate_id']}): {cl['field']} = {cl['value']}. {cl.get('evidence', '')}".strip(),
                "source_url": src.get("url"), "source_title": src.get("title"),
            })
        for x in c.get("contradictions", []):
            out.append({"candidate_id": c["candidate_id"], "text": f"{c['display_name']} ({c['candidate_id']}): {x['detail']}",
                        "source_url": None, "source_title": "contradiction engine"})
    for s in result.get("summaries", []):
        if s.get("summary"):
            out.append({"candidate_id": None, "text": f"Search '{s['query']}': {s['summary'][:1500]}",
                        "source_url": None, "source_title": "search summary"})
    return out


def index(search_id: str, result: dict, provider) -> int:
    chunks = chunks_from_result(result)
    if not chunks:
        return 0
    vectors.replace(search_id, chunks, provider.embed([c["text"] for c in chunks]))
    return len(chunks)


def ask(search_id: str, question: str, provider, k: int = 6) -> dict:
    blocked = find_blocked_terms(question)
    if blocked:
        raise ValueError(f"Questions about sensitive data are not allowed ({', '.join(blocked)}).")
    hits = vectors.search(search_id, provider.embed([question])[0], k)
    return {"answer": provider.answer(question, hits),
            "citations": [{f: h[f] for f in ("text", "source_url", "source_title", "candidate_id", "score")}
                          for h in hits]}
