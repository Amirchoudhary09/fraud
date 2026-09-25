"""Gemini provider.

- search(): Gemini with "Grounding with Google Search" -> answer text + cited web sources.
- extract_candidates(): Gemini (no tools, JSON output) turns the cited snippets into
  structured candidates. Every claim must point at a source id we supplied; claims
  citing unknown sources are dropped, so the model cannot invent evidence.
"""
import json

import httpx

from ..models import Candidate, Claim, IdentityInput, SourceRef
from ..privacy import redact
from .base import SearchResult, SearchSnippet

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SEARCH_PROMPT = """Use Google Search to find PUBLICLY available professional information for: {query}

List each distinct person or public profile you find. For each, state only what public
sources say: full name, platform/website, company, college/university, job role, city.
If sources disagree, mention both. Never include phone numbers, email addresses,
home addresses, government ID numbers, or anything from private accounts."""

EXTRACT_PROMPT = """You are an evidence extractor for an identity-resolution tool.

Target identity supplied by the user:
{identity}

Below are search snippets. Each snippet lists the source ids that support it.
Sources:
{sources}

Snippets:
{snippets}

Group the information into distinct real-world people (candidates). Include people who
look different from the target too — do not force a match. For each candidate output
claims. Rules:
- Only use facts stated in the snippets. Do not guess.
- Every claim MUST have a "source_id" from the Sources list that supports it.
- field is one of: name, company, college, role, location, username, other.
- evidence is a short quote/paraphrase from the snippet.
- Never output phone numbers, emails, street addresses or ID numbers.

Return JSON only:
{{"candidates": [{{"display_name": str, "platform": str,
  "claims": [{{"field": str, "value": str, "evidence": str, "source_id": str}}]}}]}}"""


class ProviderError(RuntimeError):
    pass


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 60.0):
        self.api_key = api_key
        self.model = model
        self.client = httpx.Client(timeout=timeout)

    def _call(self, body: dict) -> dict:
        resp = self.client.post(
            API.format(model=self.model),
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json=body,
        )
        if resp.status_code != 200:
            try:
                msg = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                msg = resp.text
            raise ProviderError(f"Gemini API error {resp.status_code}: {msg[:300]}")
        return resp.json()

    def search(self, query: str) -> SearchResult:
        data = self._call({
            "contents": [{"parts": [{"text": SEARCH_PROMPT.format(query=query)}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": 0},
        })
        cand = (data.get("candidates") or [{}])[0]
        text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        meta = cand.get("groundingMetadata", {}) or {}

        sources = []
        for chunk in meta.get("groundingChunks", []) or []:
            web = chunk.get("web") or {}
            if web.get("uri"):
                sources.append(SourceRef(url=web["uri"], title=web.get("title", "")))

        snippets = []
        for sup in meta.get("groundingSupports", []) or []:
            seg = (sup.get("segment") or {}).get("text", "")
            idx = [i for i in sup.get("groundingChunkIndices", []) if 0 <= i < len(sources)]
            if seg and idx:
                snippets.append(SearchSnippet(text=redact(seg), sources=[sources[i] for i in idx]))

        return SearchResult(query=query, summary=redact(text), snippets=snippets, sources=sources)

    def extract_candidates(self, identity: IdentityInput, results: list[SearchResult]) -> list[Candidate]:
        # Number every distinct source so the model can only cite these.
        source_ids: dict[str, SourceRef] = {}
        by_url: dict[str, str] = {}
        snippet_lines = []
        for r in results:
            for s in r.snippets:
                ids = []
                for src in s.sources:
                    if src.url not in by_url:
                        sid = f"S{len(by_url) + 1}"
                        by_url[src.url] = sid
                        source_ids[sid] = src
                    ids.append(by_url[src.url])
                snippet_lines.append(f"- [{', '.join(ids)}] {s.text}")

        if not snippet_lines:
            return []

        prompt = EXTRACT_PROMPT.format(
            identity=identity.model_dump_json(exclude_none=True),
            sources="\n".join(f"{sid}: {src.title}" for sid, src in source_ids.items()),
            snippets="\n".join(snippet_lines[:200]),
        )
        data = self._call({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        })
        cand = (data.get("candidates") or [{}])[0]
        raw = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"Could not parse extraction output: {e}") from e

        return parse_candidates(parsed, source_ids)


VALID_FIELDS = {"name", "company", "college", "role", "location", "username", "other"}


def parse_candidates(parsed: dict, source_ids: dict[str, SourceRef]) -> list[Candidate]:
    out = []
    for i, c in enumerate(parsed.get("candidates", []) or []):
        claims = []
        for cl in c.get("claims", []) or []:
            src = source_ids.get(str(cl.get("source_id", "")).strip())
            field = str(cl.get("field", "")).lower()
            value = redact(str(cl.get("value", "")).strip())
            if not src or field not in VALID_FIELDS or not value:
                continue  # uncited or malformed claim -> dropped
            claims.append(Claim(field=field, value=value,
                                evidence=redact(str(cl.get("evidence", "")))[:400], source=src))
        if not claims:
            continue
        name = str(c.get("display_name") or next((x.value for x in claims if x.field == "name"), "Unknown"))
        out.append(Candidate(
            candidate_id=f"C{i + 1:03d}",
            display_name=redact(name)[:100],
            platform=str(c.get("platform") or claims[0].source.title or "web")[:60],
            profile_url=claims[0].source.url,
            claims=claims,
        ))
    return out
