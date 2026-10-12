# BigQuery analytics implementation audit

**Audit date:** 2026-10-12  
**Scope:** current `main` branch, repository structure and key backend/frontend files.  
**Change policy:** this audit was performed before implementation; work is isolated on `feat/bigquery-analytics`.

## Findings

### Existing architecture worth preserving

- FastAPI backend with repository-layer SQL access and SQLite by default; PostgreSQL is supported through `DATABASE_URL`.
- Next.js 16 + TypeScript frontend with an authenticated API client and an existing Administration page.
- Role-based authorization is enforced on the server through `need(permission)`.
- Append-only/hash-chain audit logging, encrypted evidence, privacy filtering, retention controls, and a substantial CI pipeline already exist.
- Existing evaluation metrics are derived from reviewer feedback and are intended to evaluate matching quality; they are not a general operational analytics warehouse.

### Gap confirmed

- No BigQuery client dependency, BigQuery configuration, warehouse schema, ETL/snapshot service, API endpoints, or UI integration was present in the reviewed files.
- Current admin dashboard metrics are operational counts over recent windows. There is no durable, historical analytics snapshot in a cloud warehouse.
- README describes the live Railway deployment as not verified. A code change alone cannot prove a cloud deployment is healthy.

### Design decisions

1. BigQuery is an **analytics sink**, not the operational database. Authentication, cases, evidence, and transactional writes stay in SQLite/PostgreSQL.
2. Export **aggregate counts only**: no emails, names, search terms, profile URLs, evidence text, evidence hashes, IPs, or case identifiers are sent to BigQuery.
3. A daily snapshot table is partitioned by `snapshot_date`; `MERGE` makes repeated syncs on the same UTC date idempotent.
4. BigQuery is optional. If not configured, the existing app remains usable and the UI explains that setup is needed.
5. Warehouse reads and syncs use new server-side permissions and are audited. Secrets are environment-only and never committed.
6. Tests cover the unconfigured path, authorization, and aggregate payload privacy. Live BigQuery and cloud deployment verification require valid cloud credentials and a provisioned Google Cloud dataset.

## Implementation and verification checklist

- [ ] Add optional BigQuery client dependency and environment configuration.
- [ ] Add aggregate snapshot, partitioned table setup, idempotent upsert, and read APIs.
- [ ] Add least-privilege permissions and audit events.
- [ ] Add admin UI for configuration status, sync, and recent snapshots.
- [ ] Add unit/API tests and run repository CI.
- [ ] Document Google Cloud setup, IAM, cost controls, and deployment variables.
- [ ] Verify a live sync and deployment only after valid cloud credentials are configured.
