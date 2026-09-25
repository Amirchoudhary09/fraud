# Public Identity Evidence Platform (MVP)

Given a name plus optional company / college / role / city, the app searches the **public web**,
groups what it finds into candidate people, and scores each candidate with an **explainable
evidence score**. Every claim links to its public source, and the app flags contradictions
between sources.

> A score is a heuristic evidence score, **not a probability and not proof of identity**.
> Every result needs human review.

## Aapko khud kya karna hai

| # | Kaam | Kyun |
|---|------|------|
| 1 | https://aistudio.google.com par apne Google account se login karo → **Get API key** → **Create API key** | Claude aapke Google account mein login nahi kar sakta |
| 2 | `.env.example` ko copy karke `.env` banao aur `GEMINI_API_KEY=...` bharo | Key ke bina app **mock mode** (demo data) mein chalti hai |
| 3 | `.\run.ps1` chalao aur browser mein http://localhost:8000 kholo | App start karne ke liye |
| 4 | (Optional) GitHub par push karna ho to khud karo, ya Claude se kaho. `.env` kabhi commit mat karna | Push ek public action hai, isliye Claude ne khud nahi kiya |

Gemini ka free tier limited hai. Har investigation mein 4 search calls aur 1 extraction call
jaati hai (`MAX_QUERIES` se kam-zyada kar sakte ho).

## Run

```powershell
.\run.ps1                                   # creates .venv on first run, serves on :8000
.\.venv\Scripts\python.exe -m pytest -q     # tests (use mock provider, no network)
```

Requires Python 3.11+. No Node/Docker/MongoDB needed (the frontend is plain HTML/JS, the database is SQLite in `data/`).

## How it works

```
input identity
  → planner.py          builds 2-4 targeted search queries
  → providers/gemini.py  Gemini + "Grounding with Google Search" → text + cited source URLs
  → providers/gemini.py  Gemini (JSON mode) extracts candidates; every claim must cite a
                         source id we supplied, uncited claims are dropped
  → matching.py          deterministic rule engine: name/company/college/role/city/username
                         similarity (fuzzy, acronyms like GLBITM, role synonyms),
                         corroboration across sources, contradiction detection
  → score 0-100 + "Why this score?" breakdown, stored in SQLite
```

The LLM only **extracts** facts. All **scoring** happens in plain Python, so every point can be traced to a signal and its sources.

| Signal | Points |
|---|---|
| Name match / partial / mismatch | +30 / +15 / −30 |
| Company | +25 / +12 / −10 |
| College | +20 / +10 / −8 |
| Role | +10 / +5 / −4 |
| Username | +10 / +5 / −4 |
| City | +5 / +2 / −2 |
| Extra independent sources | +5 each, max +10 |
| Each contradiction (name, college, city) | −5 |

Score = points earned ÷ points possible for the fields you entered. Fields with no public data count 0 ("unknown").
Several different companies or roles are **not** flagged as contradictions, because they are usually career history.

## Features

- Case list with live progress (background job + polling)
- Candidate cards: score, band (strong ≥75 / possible ≥45 / weak), **Why this score?**, contradictions, cited evidence table
- Reviewer feedback per candidate (correct / wrong / insufficient evidence), stored for future evaluation
- Printable evidence report (`/api/investigations/{id}/report`, save as PDF from the browser)
- Delete case (removes evidence + feedback)

## Privacy & safety guardrails

- Requests asking for phone numbers, addresses, ID numbers, passwords, leaked data or private accounts are rejected (`privacy.py`)
- Phone numbers, emails, Aadhaar/PAN-like numbers are redacted from all evidence before storage
- Only search-API results are used: no scraping, no login-walled content
- The user must choose a purpose and accept a responsible-use statement; both are written to `audit_log`
- Per-IP rate limit, plus an audit log of create / delete / feedback / blocked requests
- UI and report state clearly that results are possible matches, not proof of identity

## API

| Method | Path | |
|---|---|---|
| GET | `/api/health` | mode (mock/gemini) and model |
| POST | `/api/investigations` | `{identity:{name,...}, purpose, acknowledged:true}` → `{id}` |
| GET | `/api/investigations` | list cases |
| GET | `/api/investigations/{id}` | status, stage, result, feedback |
| DELETE | `/api/investigations/{id}` | delete case |
| POST | `/api/investigations/{id}/candidates/{cid}/feedback` | `{verdict}` |
| GET | `/api/investigations/{id}/report` | HTML report |

Interactive docs: http://localhost:8000/docs

## Not built yet (next phases)

- **No authentication or user accounts yet.** Keep it on localhost. Add login before hosting it anywhere.
- Embedding-based matching, evidence graph, comment/abuse analysis, LangGraph agents, Redis/Celery, evaluation dataset & confidence calibration
- Page fetching beyond search snippets (only the grounded snippets are used today)
