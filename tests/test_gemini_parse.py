import json

import httpx

from app.models import IdentityInput, SourceRef
from app.providers.gemini import GeminiProvider, parse_candidates

S = {"S1": SourceRef(url="https://r/1", title="linkedin.com"), "S2": SourceRef(url="https://r/2", title="github.com")}


def test_drops_uncited_and_invalid_claims():
    parsed = {"candidates": [
        {"display_name": "Amir", "platform": "LinkedIn", "claims": [
            {"field": "company", "value": "WASP3D", "evidence": "at WASP3D", "source_id": "S1"},
            {"field": "college", "value": "GLBITM", "evidence": "made up", "source_id": "S9"},  # unknown source
            {"field": "phone", "value": "x", "source_id": "S1"},                                 # invalid field
        ]},
        {"display_name": "Nobody", "claims": [{"field": "name", "value": "Nobody", "source_id": "S7"}]},
    ]}
    out = parse_candidates(parsed, S)
    assert len(out) == 1
    assert [(c.field, c.value) for c in out[0].claims] == [("company", "WASP3D")]


def test_search_and_extract_with_fake_api():
    """Exercise the real HTTP code path against a fake Gemini endpoint."""
    grounded = {"candidates": [{
        "content": {"parts": [{"text": "Amir Choudhary is a Software Developer at WASP3D. Phone 9876543210."}]},
        "groundingMetadata": {
            "groundingChunks": [{"web": {"uri": "https://r/1", "title": "linkedin.com"}}],
            "groundingSupports": [{"segment": {"text": "Amir Choudhary is a Software Developer at WASP3D."},
                                   "groundingChunkIndices": [0]}],
        },
    }]}
    extracted = {"candidates": [{"content": {"parts": [{"text": json.dumps({"candidates": [
        {"display_name": "Amir Choudhary", "platform": "LinkedIn", "claims": [
            {"field": "company", "value": "WASP3D", "evidence": "Developer at WASP3D", "source_id": "S1"}]}]})}]}}]}
    calls = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.headers["x-goog-api-key"] == "k"
        return httpx.Response(200, json=grounded if "tools" in body else extracted)

    p = GeminiProvider("k", "gemini-test")
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    r = p.search('"Amir Choudhary" WASP3D')
    assert "[phone redacted]" in r.summary
    assert r.snippets[0].sources[0].title == "linkedin.com"

    cands = p.extract_candidates(IdentityInput(name="Amir Choudhary"), [r])
    assert cands[0].claims[0].source.url == "https://r/1"
    assert calls[1]["generationConfig"]["responseMimeType"] == "application/json"


def test_api_error_is_reported():
    p = GeminiProvider("bad", "m")
    p.client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"error": {"message": "API key not valid"}})))
    try:
        p.search("x")
    except Exception as e:
        assert "API key not valid" in str(e)
    else:
        raise AssertionError("expected error")
