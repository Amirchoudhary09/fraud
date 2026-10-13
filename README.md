# Public Identity & Evidence Intelligence Platform

A security-first, auditable platform for:

1. **Public identity discovery.** It searches publicly available information using identity clues and finds possible public profiles.
2. **Identity resolution.** It compares candidates and gives each one an explainable evidence score ("Why this score?"), including contradictions between sources.
3. **Incident analysis.** It records abusive, threatening or scam comments as cases → incidents → evidence (SHA-256 hashed and encrypted) → AI indicators → reports.

> A score is a heuristic evidence score, **not a probability and not proof of identity**. Content
> indicators are **not legal findings**. Every result needs human review.

---

## 🧑‍💻 Required Setup (Step-by-Step Checklist)

The code changes have been pushed to GitHub. The following steps require access to your personal accounts or secrets, so you must complete them yourself. **Follow the steps in order, from top to bottom.**

### A. Immediate security steps (~5 minutes)

- [ ] **1. Rotate your Gemini API key.** The previous key was shared in a chat.
  Go to https://aistudio.google.com → **API keys** → delete the old key → select **Create API key** to generate a new one.
  Never share the new key, paste it into chats, or commit it to GitHub. Add it only to Railway Variables (step 5).
- [ ] **2. Remove obsolete local folders.** The code is available on GitHub, so these old folders are no longer needed:
  - `C:\Users\amir\AppData\Local\Temp\claude\C--Users-amir\8ed568c5-650d-49c1-a52f-c3fbafd020c1\scratchpad\work`: iski `backend\.env` mein purani key hai.
  - `C:\Users\amir\projects\identity-platform`: purana MVP.

### B. Generate secrets (~3 minutes)

- [ ] **3.** Run these three commands on your computer and save all three outputs somewhere **secure** (a password manager is recommended):
  ```powershell
  python -c "import secrets;print(secrets.token_urlsafe(48))"                               # JWT_SECRET
  python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"  # EVIDENCE_KEY
  python -c "import secrets;print(secrets.token_urlsafe(32))"                               # IP_HASH_SALT
  ```
  ⚠️ If you lose `EVIDENCE_KEY`, stored evidence can never be decrypted. Keep a secure backup.
  (The second command requires `pip install cryptography`.)

### C. Deploy to Railway (~10 minutes)

- [ ] **4.** Sign in at https://railway.com → **New Project** → **Deploy from GitHub repo** → select `Amirchoudhary09/fraud`.
- [ ] **5. Configure the backend service**
  - Settings → **Root Directory** = `backend`
  - Settings → **Volumes** → **Add Volume**, mount path `/data`
  - **Do not create a public domain.** The backend should remain accessible only through the private network.
  - **Variables** mein yeh daalo:
    ```
    GEMINI_API_KEY=<step 1 wali nayi key>
    JWT_SECRET=<step 3>
    EVIDENCE_KEY=<step 3>
    IP_HASH_SALT=<step 3>
    DATA_DIR=/data
    MFA_REQUIRED_ROLES=super_admin,security_admin,investigator
    MAX_QUERIES=3
    MAX_JUDGED_CANDIDATES=2
    ```
    The final two settings help keep usage within Gemini's free-tier limits.
- [ ] **6. Configure the frontend service:** **+ New** → **GitHub Repo** → select the same repository
  - Settings → **Root Directory** = `frontend`
  - Variables: `BACKEND_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000`, aur backend service mein `PORT=8000` bhi add karo.
  - Settings → Networking → **Generate Domain**. Yahi aapki app ka URL hai.
- [ ] **7.** The deployment logs should show both services as "Active/healthy". If they do not, open **Deployments → View logs**.

### D. First-time application setup (~5 minutes)

- [ ] **8.** Open the frontend URL → **Create the first account**. This account becomes `super_admin`. Use a strong password of at least 10 characters.
- [ ] **9.** Go to **Account** → **Set up MFA** → scan the QR code with Google Authenticator or Microsoft Authenticator on your phone → enter the code to confirm.
- [ ] **10.** Create team member accounts from the **Admin** page and assign each person the least-privileged role they need:
  - `analyst`: cases/incidents
  - `investigator`: export
  - `auditor`: sirf audit log
  - `user`: sirf search
- [ ] **11.** Run a test search for your own name in **Searches**. The mock-mode banner should **not** appear, and results should include real sources.
- [ ] **12.** Select **Security → Audit log → Verify hash chain**. The result should say "Chain intact".

### E. Recommended follow-up steps

- [ ] **13. Cloudflare (WAF/DDoS):**
  1. Domain Cloudflare par daalo.
  2. Railway domain par proxied CNAME banao.
  3. SSL ko **Full (strict)** par rakho.
  4. **Managed WAF** aur **Bot Fight Mode** on karo.
  5. `/bff/*` aur `/api/auth/*` par rate-limit rule lagao.
- [ ] **14. Backups:** Railway volume `/data` ka regular backup lo. Isme databases, encrypted evidence aur audit log hain.
- [ ] **15. Optional integrations.** Sab off hain jab tak variables set na ho. Poori list `backend/.env.example` mein hai:
  - **Company login (SSO):** `OIDC_*`. Google Workspace / Microsoft Entra mein redirect URI `https://<frontend-domain>/bff/oidc/callback` rakho.
  - **SIEM (Splunk/Elastic):** `SIEM_*`
  - **Tamper-proof audit copy:** `WORM_S3_*`. S3 bucket **Object Lock ON** ke saath banana hoga.
  - **Neo4j graph DB:** `NEO4J_*`
  - **Zyada users/traffic:** Railway par PostgreSQL + Redis add karo, `DATABASE_URL` + `REDIS_URL` set karo, aur ek worker service (`./start.sh worker`) chalao. Details neeche "Running more than one backend replica" section mein hain.
- [ ] **16. Accuracy numbers:** Searches ke results par reviewers "Correct / Wrong" dabayein. 30+ reviews ke baad **Admin → Evaluation** mein asli accuracy dikhegi, aur **Fit calibration** se confidence calibrated ho jayega.

### Kabhi mat karna

- ❌ API keys, `.env` file ya secrets GitHub par commit karna, ya chat/email mein bhejna
- ❌ Backend ko public domain dena
- ❌ Search result ko "proof of identity" maanna. Yeh sirf public evidence hai, final faisla insaan karega.
- ❌ Private data maangna (phone number, ghar ka pata, ID numbers). App aisi requests block karti hai, aur yeh log bhi hoti hain.

**Troubleshooting:** Check the Railway logs, `GET /api/health` (open the frontend URL followed by `/api/health`), and the **Security** page, which displays security events and errors.

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
  tests/                    backend test suite (mock mode, no network)
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

## ✅ What is implemented (frontend)

Next.js 16 + TypeScript. Details are in [frontend/README.md](frontend/README.md).

- **Login flow.** Covers first-account setup, sign in, and the MFA code step.
- **Session security.** The refresh token is kept only in an **httpOnly, SameSite=Strict cookie**. The access token lives in memory only. Session endpoints check the Origin header against CSRF.
- **Pages.**
  - Dashboard: my searches (who → whom, when, case, purpose, status) and my cases.
  - Searches: live progress, candidates with **"Why N?"**, contradictions, cited evidence (opening it is audited), reviewer verdicts, **evidence graph**, **ask the evidence**, agent trace.
  - Cases: incidents (with AI indicators and "find public profile of @handle"), evidence (text / public URL / file, SHA-256, integrity verify, download), searches in the case, **evidence timeline**, access (grant/revoke, time limits, access history), reports (with hashes).
  - Security: dashboard, security events (acknowledge / resolve), break-glass approvals, audit log viewer with **hash-chain verification**.
  - Admin: users and roles, MFA reset, evaluation, calibration, retention.
  - Account: MFA enrolment with a QR code generated in the browser.
- **Reports.** Rendered in a **sandboxed iframe** (no scripts). PDF export needs the `evidence.export` permission and is audited.
- **Browser hardening.** Security headers (CSP, frame-ancestors none, HSTS, nosniff) and no `X-Powered-By` header.

---

## ▶️ Run locally

```powershell
# backend (http://localhost:8000, API docs at /docs)
cd backend
.\run.ps1
.\.venv\Scripts\python.exe -m pytest -q          # backend tests, mock mode, no network

# frontend (http://localhost:3000); needs Node 20+
cd frontend
npm install
$env:BACKEND_URL="http://localhost:8000"; npm run dev

# end-to-end tests (start their own backend + frontend on ports 8799/3799)
npx playwright install chromium
npm run test:e2e
```

Open http://localhost:3000. The first account you create becomes `super_admin`.

---

## 🚀 Deploy on Railway (manual account setup required)

These steps require access to your Railway account and must be completed manually (about 10 minutes). The repository is configured for deployment: each service has a `Dockerfile` and a `railway.json` health check.

1. Go to https://railway.com, then **New Project → Deploy from GitHub repo → `Amirchoudhary09/fraud`**.
2. Create the **backend** service:
   - Settings → **Root Directory** = `backend`
   - Settings → **Volumes** → add a volume mounted at `/data`. It holds the databases, the encrypted evidence and the audit log.
   - Variables:
     ```
     GEMINI_API_KEY=<your key>
     JWT_SECRET=<python -c "import secrets;print(secrets.token_urlsafe(48))">
     EVIDENCE_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
     IP_HASH_SALT=<any long random string>
     DATA_DIR=/data
     MFA_REQUIRED_ROLES=super_admin,security_admin,investigator
     ```
   - Do **not** give it a public domain. The frontend reaches it over Railway's private network.
3. Add the **frontend** service: **+ New → GitHub repo** (same repo).
   - Settings → **Root Directory** = `frontend`
   - Variables: `BACKEND_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:${{backend.PORT}}`. If `PORT` is not set on the backend, use `:8000` and set `PORT=8000` there.
   - Settings → Networking → **Generate Domain**. This is your app URL.
4. Open the frontend URL and create the first account (it becomes super_admin). Then set up MFA under **Account**.

Keep `EVIDENCE_KEY` safe. Without it, stored evidence cannot be decrypted. With the CLI instead of the dashboard: `npm i -g @railway/cli`, `railway login`, `railway link`, `railway up`, running `railway up` from each service folder.

### Running more than one backend replica (optional)

1. Add **PostgreSQL** and **Redis** to the project (Railway → + New → Database).
2. Backend variables:
   - `DATABASE_URL=${{Postgres.DATABASE_URL}}`
   - `REDIS_URL=${{Redis.REDIS_URL}}`
   - Optional: `AUDIT_DATABASE_URL` pointing to a second Postgres database used only for the audit log.
3. Add a **worker** service from the same repo:
   - Root Directory `backend`
   - Start Command `./start.sh worker`
   - Same variables as the backend
4. Now you can raise the backend's replica count.
5. Uploaded evidence files still live on the `/data` volume, which one service owns. For several replicas, move evidence files to S3 by replacing `services/storage.py`.

### Optional integrations

These are all off unless configured. The variables are listed in `backend/.env.example`.

- **SSO:** `OIDC_*`, with redirect URI `https://<frontend>/bff/oidc/callback`
- **SIEM:** `SIEM_*`
- **WORM storage:** `WORM_S3_*`. The bucket must be created with Object Lock.
- **Neo4j:** `NEO4J_*`

### Edge protection (WAF / CDN / DDoS) and KMS

These are infrastructure settings, not code.

- **Cloudflare in front of the frontend domain:**
  1. Add the domain to Cloudflare and point a CNAME to the Railway domain (proxied).
  2. Set SSL/TLS to **Full (strict)**.
  3. Turn on the **Managed WAF ruleset** and **Bot Fight Mode**.
  4. Add a rate-limiting rule on `/bff/*` and `/api/auth/*`.
  5. Leave the backend without a public domain. It is reachable only through the frontend over Railway's private network.
- **Secrets:** Keep `JWT_SECRET`, `EVIDENCE_KEY` and the OIDC/SIEM secrets in Railway variables, or in a cloud secrets manager (AWS Secrets Manager, GCP Secret Manager, Azure Key Vault) injected as environment variables. Rotate them by redeploying with new values. Rotating `EVIDENCE_KEY` requires re-encrypting stored evidence.

---

## 🚧 Status / not done yet

### ❌ Not implemented: multi-platform public footprint (all of a person's social accounts and history)

**Original request:** Aggregate a person's accounts across around 40 platforms (Instagram, Facebook, LinkedIn, X, YouTube, TikTok, Reddit, GitHub, and others), follow published links to discover more accounts, and retrieve historical account details such as old usernames, bios, posts, and timelines.

**Why this was not implemented:**
- **Stalking risk:** Aggregating someone's accounts and history into one place creates a detailed personal dossier. It could be misused for stalking, doxxing, or harassment without the person's knowledge.
- **Platform terms and login restrictions:** Much of the data on Instagram, Facebook, LinkedIn, and Snapchat is behind login walls, and their terms restrict scraping.
- **Legal risk:** Collecting and profiling personal information in this way without consent may create legal risks under India's Digital Personal Data Protection Act, 2023.
- **Code revert kiya:** Ek version (commit `a782b7f`) bana kar push hua tha, lekin use commit `2fbd034` se revert kar diya gaya. Woh code history mein hai, lekin app mein active nahi hai.

**Current standard-mode behavior:** The app uses a name and other clues to search broadly across the public web. Query planning mixes identity clues with domain-diverse searches covering professional networks, social networks, code-hosting sites, video platforms, forums, blogs, news, portfolios, and other websites. This is web discovery through Google Search grounding, not a dedicated integration with every platform, so coverage depends on what is publicly indexed and returned. Each claim includes a source, the interface explains "Why this score?", and contradictions are shown for human review. In harassment cases, investigators can search for an incident author's public profile from within the case. This action is recorded in the audit log and can support platform or law-enforcement reports.

### ✅ / ⏳ Remaining status

- [x] Backend: every feature listed above, with 70 automated tests.
- [x] Frontend: every page listed above. `next build` passes. End-to-end checked locally: setup → httpOnly refresh cookie → refresh → search through the proxy → PDF → logout.
- [x] Railway files: Dockerfiles, `railway.json`, `.dockerignore`.
- [x] **Docker images verified in CI**: both images are built, run together on a private network, and smoke-tested (health, proxy, non-root user, CSRF block).
- [x] **Redis (optional, `REDIS_URL`)**: shared sliding-window rate limits and a reliable job queue. Jobs held by a crashed worker are re-queued once its heartbeat expires. Run `python -m app.workers.worker` as a separate service. Tested with fakeredis, and against a real Redis in CI.
- [x] **SIEM export** (`SIEM_WEBHOOK_URL`): audit events are shipped in order from a cursor, as generic JSON or Splunk HEC, with an auth header. The cursor only advances after the SIEM accepts a batch, so delivery is at-least-once and nothing is skipped. Status and lag are at `GET /api/admin/exports`.
- [x] **WORM storage** (`WORM_S3_BUCKET`): audit segments are written to S3/MinIO with **Object Lock COMPLIANCE**, a retention date and a SHA-256 checksum, with chain hashes in the object metadata. CI checks that a locked segment cannot be deleted, using an S3 server that emulates Object Lock (moto, since MinIO stopped publishing public images). It has not been tested on real AWS S3.
- [x] **OIDC single sign-on** (`OIDC_*`): works with Google Workspace, Microsoft Entra ID, Okta, Auth0 and Keycloak.
  - Authorization code flow with PKCE, single-use `state`, `nonce` check, and id_token signature verified against the IdP's JWKS (`iss`/`aud`/`exp` checked too).
  - Only verified emails are accepted, with an optional email-domain allowlist and optional MFA-at-IdP (`amr`).
  - The IdP subject is bound to one local account.
  - The state is also tied to the browser by a cookie, which blocks login CSRF.
  - Tested with 13 backend tests (forged, expired, wrong-audience and wrong-key tokens, account takeover) and 2 browser E2E tests against a fake IdP.
- [x] **Neo4j**:
  - `GET /api/searches/{id}/graph.cypher` downloads the evidence graph as a Cypher script. Every value is escaped and labels come from an allowlist, so web data cannot inject Cypher.
  - `POST /api/searches/{id}/graph/neo4j` pushes the graph into a live Neo4j (`NEO4J_URI`) with parameterised, idempotent MERGE. Both actions are audited, and CI checks the push against a real Neo4j.
- [x] **PostgreSQL** (`DATABASE_URL`, optional `AUDIT_DATABASE_URL`):
  - App data and the audit log can both live in Postgres. SQLite stays the default.
  - On Postgres the audit table is protected by PL/pgSQL triggers that block UPDATE, DELETE and TRUNCATE.
  - Chain appends are serialised with an advisory lock, so several replicas cannot fork the hash chain.
  - The full backend suite runs on PostgreSQL 16 locally and in CI.
  - Together with Redis, this is the setup for running more than one API replica.
- [x] **Real Gemini, verified locally with a real API key.** A self-check search for "Amir Choudhary / WASP3D / GLBITM / Software Developer" ran the whole pipeline:
  - Google-grounded search, extraction of cited claims, embeddings and LLM review all worked.
  - It found one public candidate: a GitHub profile, "Software Development Engineer" at WASP3D, scored 71/100 ("possible"). No college was found publicly, so that signal stayed "unknown".
  - The free tier hit its per-minute quota on the next call. Those errors are now retried and then returned as a clear 503 with `Retry-After`.
  - Grounded search is not deterministic: the same query sometimes returns sources and sometimes not.
- [ ] **Not verified by Claude:**
  - A real Railway deploy: needs your login.
  - Real AWS S3 Object Lock: tested with the moto emulator only.
- **Gemini free tier:** one search makes about 8–12 model calls (4 searches, extraction, embeddings, up to 5 LLM reviews). To stay within free-tier limits, lower `MAX_QUERIES` and `MAX_JUDGED_CANDIDATES`, set `LLM_JUDGE=0`, or enable billing.
- [x] **Playwright end-to-end tests** (`frontend/e2e`, 6 flows in real Chromium, including SSO and login-CSRF): first-account setup and httpOnly session; search with "Why N?", graph and ask; case → incident → evidence integrity → timeline; MFA enrolment by QR code, then MFA sign-in and audit-chain verification.
- [x] **GitHub Actions CI** (`.github/workflows/ci.yml`): backend tests, frontend lint/type-check/build, and the E2E suite on every push and pull request.
- [ ] Needs infrastructure beyond one container, so intentionally not in V1:
  - Cloud WAF/CDN/DDoS: an infrastructure setting. See "Edge protection" above for the Cloudflare steps.
  - KMS/secrets manager: an infrastructure setting. See "Edge protection" above.
  - A dedicated vector database (vectors are stored in SQLite today, and brute-force search is fine per investigation).
  - MongoDB (PostgreSQL is supported, see above).
- [ ] **Evaluation numbers:** `eval/sample_dataset.json` is **synthetic**. Real accuracy figures need a labelled dataset from reviewed searches (`/api/admin/eval-dataset`).


## Google BigQuery analytics

The optional BigQuery warehouse stores privacy-preserving daily aggregate snapshots. It complements, rather than replaces, the operational SQLite/PostgreSQL database. Setup, IAM, deployment variables, daily scheduling, and verification steps are documented in [docs/BIGQUERY_ANALYTICS.md](docs/BIGQUERY_ANALYTICS.md). The implementation audit and explicit scope are in [docs/BIGQUERY_ANALYTICS_AUDIT.md](docs/BIGQUERY_ANALYTICS_AUDIT.md).
