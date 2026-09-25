# Public Identity & Evidence Intelligence Platform

A security-first, auditable platform for:

1. **Public identity discovery.** It searches publicly available information using identity clues and finds possible public profiles.
2. **Identity resolution.** It compares candidates and gives each one an explainable evidence score ("Why this score?"), including contradictions between sources.
3. **Incident analysis.** It records abusive, threatening or scam comments as cases → incidents → evidence (SHA-256 hashed and encrypted) → AI indicators → reports.

> A score is a heuristic evidence score, **not a probability and not proof of identity**. Content
> indicators are **not legal findings**. Every result needs human review.

---

## 🧑‍💻 Aapko khud kya karna hai

| # | Kaam | Kyun |
|---|------|------|
| 1 | https://aistudio.google.com par apne Google account se login karo → **Get API key** → **Create API key** | Claude aapke Google account mein login nahi kar sakta. Key ke bina app **mock mode** (demo data) mein chalti hai |
| 2 | `backend/.env.example` ko copy karke `backend/.env` banao aur `GEMINI_API_KEY=...` bharo | Real Google search + Gemini ke liye |
| 3 | Production ke liye `JWT_SECRET`, `EVIDENCE_KEY`, `IP_HASH_SALT` generate karke set karo (commands `.env.example` mein hain) | Secrets code mein nahi rakhe jaate |
| 4 | Railway par deploy: neeche **Deploy on Railway** dekho. `railway login` aapko khud karna hoga | Claude aapke Railway account mein login nahi kar sakta |
| 5 | Pehli baar app kholne par **first account** banao. Wahi `super_admin` banta hai | Setup ke baad sirf admin hi naye users bana sakta hai |

---

## 📦 Repository layout

```
backend/                    FastAPI API (Python 3.12)
  app/
    main.py                 wiring only
    api/                    HTTP layer
      deps.py               authentication, permission checks (RBAC), AUTHZ_DENIED audit
      access.py             case-level access (members, break-glass), search ownership
      middleware.py         request id, body-size limit, security headers, error counts
      routes/               auth, me, searches, cases, admin
    core/                   config, database, audit_store (tamper-evident), security (JWT/TOTP),
                            crypto (evidence encryption), permissions, privacy filter, rate limit
    schemas/                pydantic request/response models
    repositories/           the ONLY code that runs SQL (users, searches, cases, incidents,
                            evidence, entities/relationships, reports, security_events, vectors)
    services/               business logic: matching, similarity, contradictions, embeddings,
                            calibration, graph, rag, comments (indicators), incidents, evidence,
                            safe_fetch (SSRF-safe), monitoring, audit, timeline, retention, intake
    agents/                 LangGraph supervisor + search/evidence/matching/report agents,
                            least-privilege toolboxes
    providers/              Gemini (search grounding, extraction, embeddings, judge) + offline mock
    reports/                report builder -> HTML and PDF renderers
    evaluation/             metrics (precision/recall/F1/FMR/ECE/Brier), dataset from feedback
    workers/                background job queue
  tests/                    70 tests (mock mode, no network)
  eval/sample_dataset.json  SYNTHETIC labelled data for the evaluation pipeline
frontend/                   Next.js 16 + TypeScript UI (backend-for-frontend proxy at /api/*)
```

---

## ✅ What is implemented (backend)

### Discovery, resolution and explanation
- **Search planner.** Builds rule-based queries. If a search round finds no candidates, LLM query expansion and broader queries run as a second round.
- **Gemini with Grounding (Google Search).** Returns text plus cited source URLs. Extraction uses JSON mode, and any claim that doesn't cite a known source is dropped.
- **Hybrid identity resolution.**
  - A rule engine handles fuzzy names, company suffixes, college acronyms (GLBITM) and role synonyms.
  - Embedding similarity adds at most +10.
  - An LLM judge adds at most ±5.
  - The rules always dominate.
- **Contradiction engine.** Flags disagreements on name, college and city. Different companies are not flagged, because that is usually career history.
- **Confidence.**
  - The score is 0–100 with a band. The UI shows "Why N?" with the points and sources behind every signal.
  - Calibration (Platt scaling or isotonic regression) only turns on after `MIN_CALIBRATION_LABELS` reviewed labels.
- **Evidence graph.** `GET /api/searches/{id}/graph` returns Target, Candidate, Company, College, Place, Role and Source nodes. Equivalent values are merged into one node.
- **RAG "ask the evidence".** `POST /api/searches/{id}/ask` returns answers with citations. Sensitive questions are blocked.
- **Multi-agent.** A LangGraph supervisor routes between the search, evidence, matching and report agents. Routing is plain code, never an LLM decision.
- **Async jobs.** The API queues each job and returns immediately. The UI polls the job's `stage`.
- **Evaluation and feedback loop.**
  - Reviewer verdicts (correct / wrong / insufficient) become a labelled dataset.
  - `/api/admin/evaluation` reports precision, recall, F1, false-match rate, false-negative rate, top-1, evidence coverage, Brier score and ECE.
  - It also suggests new weights. These are never applied automatically.
  - CLI: `python -m app.evaluation eval/sample_dataset.json --fit isotonic`

### Security and audit (spec sections 2–33)

| Requirement | Where |
|---|---|
| Unique users, PBKDF2 passwords, **short-lived JWT (15 min)** + **rotating refresh tokens** (reuse revokes the whole session) | `core/security.py`, `routes/auth.py` |
| **MFA (TOTP)**, enforceable per role via `MFA_REQUIRED_ROLES` | `routes/auth.py` |
| **RBAC**: super_admin, security_admin, investigator, analyst, auditor, user. Checked server-side on every endpoint | `core/permissions.py`, `api/deps.py` |
| **Case-level access**: owner/editor/viewer, time-limited grants. Admin access to others' cases is audited and alerted | `api/access.py` |
| **Break-glass**: requires a reason and approval by someone else; access is temporary and always raises a high alert | `routes/cases.py`, `routes/admin.py` |
| **Immutable audit log** in a separate DB: append-only (triggers), **hash chain** (`prev_hash`/`hash`), JSONL mirror for WORM storage, `POST /api/admin/audit/verify` | `core/audit_store.py` |
| Audit events for login/logout/MFA, failed auth, **authorization denials**, searches (STARTED → QUERY_CREATED → EXECUTED → RESULTS_RECEIVED → CANDIDATE_CREATED → COMPLETED), evidence view/download, reports, exports, permission changes | `services/audit.py` |
| Search history is **separate** from the audit log. **USER ─SEARCHED→ ENTITY** relationships | `repositories/searches.py`, `entities.py` |
| **Incidents separate from searches**: 9 controlled types. USER ─CREATED_INCIDENT→ INCIDENT ─TARGETS→ ENTITY, INCIDENT ─CONTAINS→ EVIDENCE | `services/incidents.py` |
| **Evidence** has its own ID, canonical **SHA-256**, is **encrypted at rest** (Fernet), and supports integrity verification (a mismatch raises a critical alert) | `services/evidence.py`, `core/crypto.py` |
| AI analysis results stored separately as indicators, never as person labels | `analysis_results` table |
| Reports recorded with their content hash; generation and export are audited | `reports` table |
| **SSRF-safe fetching**: scheme/port/credential checks, blocks private/loopback/link-local/metadata addresses, re-validates the IP at connect time (DNS rebinding), re-checks every redirect, size and time limits, HTML sanitizer | `services/safe_fetch.py` |
| **Prompt-injection isolation**: web and user text fenced as `<untrusted_data>`; no LLM output chooses tools | `providers/gemini.py`, `agents/supervisor.py` |
| **Least-privilege agents**: each agent gets a toolbox with only its grants | `agents/tools.py` |
| **Security monitoring**: failed-login bursts, search bursts, many unrelated targets, mass export, repeated denials, privilege escalation, break-glass, integrity failures → `security_events` | `services/monitoring.py` |
| Dashboards: admin security dashboard, user "my searches", case counts, **evidence timeline**, **case access history** | `routes/admin.py`, `routes/me.py`, `services/timeline.py` |
| Rate limits, request-size limit, security headers (HSTS, nosniff, DENY frame), CSP sandbox on HTML reports, request IDs | `api/middleware.py` |
| IPs stored only as salted hashes; data retention purge (`RETENTION_DAYS`); the audit log is excluded from app retention | `core/context.py`, `services/retention.py` |
| Privacy filter: blocks requests for phone numbers, addresses, IDs, leaks and private accounts; redacts contact details and IDs from evidence | `core/privacy.py` |

---

## ▶️ Run locally

```powershell
# backend (http://localhost:8000, API docs at /docs)
cd backend
.\run.ps1
.\.venv\Scripts\python.exe -m pytest -q          # 70 tests, mock mode, no network

# frontend (http://localhost:3000); needs Node 20+
cd frontend
npm install
$env:BACKEND_URL="http://localhost:8000"; npm run dev
```

---

## 🚧 Status / not done yet

**Checkpoint push.** This commit contains the finished backend. Work continues on the items below.

- [ ] **Frontend (Next.js)**: API proxy, types and API client exist. Pages (login/MFA, searches, candidate "Why this score", graph, ask, cases/incidents/evidence, timeline, admin security dashboard) are still being built. The old plain-HTML UI was removed because it targeted the previous API.
- [ ] Railway deployment files (Dockerfiles, `railway.json`) and deploy steps.
- [ ] Items that need infrastructure beyond one container, intentionally not in V1:
  - Cloud WAF/CDN/DDoS (use Cloudflare or Railway's edge).
  - KMS/secrets manager (use Railway variables).
  - SIEM export (the audit JSONL mirror is the hook for it).
  - Redis/Celery queue (`workers/jobs.py` explains the swap).
  - Neo4j and a vector database (graph and vectors are computed and stored in SQLite).
  - MongoDB/PostgreSQL (only `repositories/` would change).
