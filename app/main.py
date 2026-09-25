import html
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .models import FeedbackRequest, InvestigationRequest
from .pipeline import run_investigation
from .privacy import find_blocked_terms

logging.basicConfig(level=logging.INFO)
STATIC = config.ROOT / "static"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init()
    yield


app = FastAPI(title="Public Identity Evidence Platform", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_hits: dict[str, deque] = defaultdict(deque)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limit(client: str):
    window, q = 3600, _hits[client]
    t = time.time()
    while q and t - q[0] > window:
        q.popleft()
    if len(q) >= config.RATE_LIMIT_PER_HOUR:
        raise HTTPException(429, "Rate limit reached. Try again later.")
    q.append(t)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "mode": "mock" if config.MOCK_MODE else "gemini", "model": config.GEMINI_MODEL}


@app.post("/api/investigations", status_code=202)
def create(req: InvestigationRequest, background: BackgroundTasks, request: Request):
    client = _client(request)
    text = " ".join(v for v in req.identity.model_dump().values() if v)
    blocked = find_blocked_terms(text)
    if blocked:
        db.audit("request_blocked", client=client, detail=f"terms={blocked}")
        raise HTTPException(400, "This tool only works with public professional information. "
                                 f"Requests for sensitive data are not allowed ({', '.join(blocked)}).")
    _rate_limit(client)
    provider = "mock" if config.MOCK_MODE else "gemini"
    inv_id = db.create_investigation(req.identity.model_dump(exclude_none=True), req.purpose, provider)
    db.audit("investigation_created", inv_id, client, f"purpose={req.purpose}")
    background.add_task(run_investigation, inv_id, req.identity)
    return {"id": inv_id}


@app.get("/api/investigations")
def list_all():
    return db.list_investigations()


def _get_or_404(inv_id: str) -> dict:
    inv = db.get_investigation(inv_id)
    if not inv:
        raise HTTPException(404, "Investigation not found")
    return inv


@app.get("/api/investigations/{inv_id}")
def get_one(inv_id: str):
    inv = _get_or_404(inv_id)
    inv["feedback"] = db.get_feedback(inv_id)
    return inv


@app.delete("/api/investigations/{inv_id}")
def delete(inv_id: str, request: Request):
    if not db.delete_investigation(inv_id):
        raise HTTPException(404, "Investigation not found")
    db.audit("investigation_deleted", inv_id, _client(request))
    return {"deleted": inv_id}


@app.post("/api/investigations/{inv_id}/candidates/{cand_id}/feedback")
def feedback(inv_id: str, cand_id: str, fb: FeedbackRequest, request: Request):
    inv = _get_or_404(inv_id)
    ids = {c["candidate_id"] for c in (inv["result"] or {}).get("candidates", [])}
    if cand_id not in ids:
        raise HTTPException(404, "Candidate not found")
    db.add_feedback(inv_id, cand_id, fb.verdict, fb.note)
    db.audit("feedback", inv_id, _client(request), f"{cand_id}={fb.verdict}")
    return {"ok": True}


@app.get("/api/investigations/{inv_id}/report", response_class=HTMLResponse)
def report(inv_id: str):
    inv = _get_or_404(inv_id)
    if inv["status"] != "done":
        raise HTTPException(409, "Investigation is not complete yet")
    return render_report(inv, db.get_feedback(inv_id))


def render_report(inv: dict, feedback: dict) -> str:
    e = html.escape
    res = inv["result"]
    rows = "".join(f"<tr><th>{e(k.title())}</th><td>{e(str(v))}</td></tr>" for k, v in inv["input"].items())
    parts = []
    for c in res["candidates"]:
        sig = "".join(
            f"<li><b>{e(s['field'])}</b> [{e(s['status'])}, {s['points']:+d}] {e(s['detail'])}"
            + "".join(f'<br><small><a href="{e(src["url"])}">{e(src["title"] or src["url"])}</a></small>'
                      for src in s["sources"]) + "</li>"
            for s in c["signals"])
        con = "".join(f"<li>⚠ {e(x['detail'])}</li>" for x in c["contradictions"]) or "<li>None found</li>"
        claims = "".join(
            f"<tr><td>{e(cl['field'])}</td><td>{e(cl['value'])}</td><td>{e(cl['evidence'])}</td>"
            f"<td><a href=\"{e(cl['source']['url'])}\">{e(cl['source']['title'] or 'source')}</a></td></tr>"
            for cl in c["claims"] if cl.get("source"))
        fb = feedback.get(c["candidate_id"], "not reviewed")
        parts.append(f"""
<section><h3>{e(c['candidate_id'])} · {e(c['display_name'])} — evidence score {c['score']}/100 ({e(c['band'])})</h3>
<p>Reviewer verdict: <b>{e(fb)}</b></p>
<h4>Why this score</h4><ul>{sig}</ul>
<h4>Contradictions</h4><ul>{con}</ul>
<h4>Evidence</h4><table><tr><th>Field</th><th>Value</th><th>Evidence</th><th>Source</th></tr>{claims}</table></section>""")
    mock = '<p class="warn">DEMO DATA — generated in mock mode, not real search results.</p>' if res.get("mock") else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Evidence report {e(inv['id'])}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#111}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}}
section{{border-top:2px solid #333;margin-top:24px}}.warn{{background:#fff3cd;padding:8px;border:1px solid #e0c060}}
.note{{background:#eef;padding:8px}}</style></head><body>
<h1>Public Evidence Report</h1>{mock}
<p class="note">This report lists publicly available information and a heuristic evidence score.
It is <b>not proof of identity</b> and not a legal finding. Every match requires human review.</p>
<h2>1. Case</h2><table><tr><th>Case ID</th><td>{e(inv['id'])}</td></tr>
<tr><th>Created (UTC)</th><td>{e(inv['created_at'])}</td></tr><tr><th>Purpose</th><td>{e(inv['purpose'])}</td></tr>
<tr><th>Provider</th><td>{e(inv['provider'])}</td></tr></table>
<h2>2. Input identity</h2><table>{rows}</table>
<h2>3. Search queries</h2><ul>{''.join(f'<li>{e(q)}</li>' for q in res['queries'])}</ul>
<h2>4. Candidates</h2>{''.join(parts) or '<p>No candidates found.</p>'}
<h2>5. All sources</h2><ol>{''.join(f'<li><a href="{e(s["url"])}">{e(s["title"] or s["url"])}</a></li>' for s in res['sources'])}</ol>
</body></html>"""
