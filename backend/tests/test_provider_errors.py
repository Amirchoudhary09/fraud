import httpx

from app.providers import gemini
from app.providers.base import ProviderError
from app.providers.mock import MockProvider

REQ = {"identity": {"name": "Quota Person"}, "purpose": "research", "acknowledged": True}


def _provider(responses: list[int], monkeypatch) -> tuple[gemini.GeminiProvider, list]:
    calls = []

    def handler(request):
        calls.append(request)
        code = responses[min(len(calls) - 1, len(responses) - 1)]
        if code == 200:
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
        return httpx.Response(code, json={"error": {"message": "Quota exceeded"}})

    p = gemini.GeminiProvider("k", "m")
    p.client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(gemini.time, "sleep", lambda s: None)
    return p, calls


def test_retries_rate_limits_then_succeeds(monkeypatch):
    p, calls = _provider([429, 503, 200], monkeypatch)
    assert p.answer("q", [{"text": "t", "source_url": None}]) == "ok" and len(calls) == 3


def test_gives_up_with_status(monkeypatch):
    p, calls = _provider([429], monkeypatch)
    try:
        p.answer("q", [{"text": "t", "source_url": None}])
        raise AssertionError("expected ProviderError")
    except ProviderError as e:
        assert e.status == 429 and len(calls) == 3


def test_no_retry_on_client_errors(monkeypatch):
    p, calls = _provider([400], monkeypatch)
    try:
        p.answer("q", [{"text": "t", "source_url": None}])
    except ProviderError as e:
        assert e.status == 400
    assert len(calls) == 1


def test_quota_errors_become_503_not_500(client, analyst_h, monkeypatch):
    sid = client.post("/api/searches", json=REQ, headers=analyst_h).json()["id"]

    class Exhausted(MockProvider):
        def answer(self, question, chunks):
            raise ProviderError("Gemini API error 429: quota", status=429)

    import app.api.routes.searches as routes
    monkeypatch.setattr(routes, "get_provider", lambda: Exhausted())
    r = client.post(f"/api/searches/{sid}/ask", json={"question": "Which company?"}, headers=analyst_h)
    assert r.status_code == 503 and "rate limit" in r.json()["detail"] and r.headers["retry-after"] == "60"
