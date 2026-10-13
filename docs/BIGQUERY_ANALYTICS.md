# Google BigQuery analytics

This integration adds a **count-only analytics warehouse**. Operational records remain in SQLite/PostgreSQL. The service exports one daily UTC snapshot with counts for users, cases, searches, incidents, evidence, and reviewer feedback. It does not export user emails, identity clues, normalized search queries, candidate names/URLs, case IDs, evidence content or hashes, or IP data.

## 1. Create a Google Cloud dataset

1. Select/create a Google Cloud project and enable the BigQuery API. BigQuery requires billing to be enabled on the project; set budgets and usage alerts before production use.
2. Create a dataset named `fraud_analytics` in a chosen location (for example `US`). Keep the dataset location consistent with your warehouse configuration.
3. Create a dedicated service account for this application. Grant:
   - **BigQuery Job User** (`roles/bigquery.jobUser`) at the project level, to run query jobs.
   - **BigQuery Data Editor** (`roles/bigquery.dataEditor`) on the analytics dataset, to create and update the snapshot table.
   Do not grant project Owner or Editor.
4. For local development, use Application Default Credentials. In production, prefer workload identity where the hosting environment supports it. Otherwise store service-account JSON only as a deployment secret in `BIGQUERY_CREDENTIALS_JSON`; never commit it.

The backend creates `daily_platform_metrics` inside the dataset on the first sync. The table is partitioned by `snapshot_date` and the `MERGE` updates the same day's row rather than duplicating it.

## 2. Environment variables

Set these on the **backend** service only:

```dotenv
BIGQUERY_PROJECT=your-gcp-project-id
BIGQUERY_DATASET=fraud_analytics
BIGQUERY_LOCATION=US
# Optional if the host does not provide Application Default Credentials:
BIGQUERY_CREDENTIALS_JSON=<service-account-json-as-a-secret>
```

The app remains operational if these variables are absent. The admin UI reports that the warehouse needs configuration. Do not put BigQuery credentials in the frontend/Vercel project.

## 3. Run a sync

- Admin UI: open **Administration → BigQuery analytics warehouse** and select **Sync aggregate snapshot**. This requires the `analytics.sync` permission.
- CLI: from the `backend` directory run `python -m app.analytics_sync`. This exits non-zero if the dataset or credentials are unavailable.
- Read recent snapshots through the protected `GET /api/admin/warehouse/metrics` endpoint. Sync is audited as `WAREHOUSE_SYNC_COMPLETED` or `WAREHOUSE_SYNC_FAILED`.

For daily snapshots, create a Render Cron Job (or equivalent scheduled job) using the same repository, backend root directory, Python environment, database URL, and BigQuery secrets; run `python -m app.analytics_sync` once per day at an off-the-hour UTC time such as 00:07. For production, use PostgreSQL as the operational database so the cron job and API share the same data. Do not run a second SQLite database in the cron container and expect it to reflect the API's data.

## 4. Analytics semantics

Each row represents a point-in-time count snapshot for one UTC calendar date. Counts include all retained operational rows at sync time; 24-hour counts are rolling windows relative to `generated_at`. These are operational measures, not fraud probabilities or claims about individual people. The app's separate matching evaluation endpoint remains the source for reviewer-labelled precision/recall/F1 and calibration.

## 5. Testing and go-live checklist

- [ ] CI passes backend tests, frontend lint/typecheck/build, E2E tests, and container smoke tests.
- [ ] Set `BIGQUERY_PROJECT`, `BIGQUERY_DATASET`, and credentials on the backend only.
- [ ] Verify the service account can create/query jobs and write only to the analytics dataset.
- [ ] Run one manual sync and confirm exactly one row exists for today's `snapshot_date`.
- [ ] Run sync a second time and confirm it updates the same row (idempotence).
- [ ] Confirm the admin UI displays snapshots and a non-admin cannot sync.
- [ ] Configure the scheduled job and alert on non-zero exit status.
- [ ] Set BigQuery billing budgets/alerts and review query/storage costs.
- [ ] Confirm production API health and deployment status independently; a passing CI run is not proof of a live cloud deployment.
