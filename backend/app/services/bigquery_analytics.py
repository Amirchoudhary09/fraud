"""Privacy-preserving aggregate analytics snapshots for Google BigQuery.

The warehouse deliberately receives counts and UTC snapshot metadata only. It never exports
identity search inputs, candidate data, evidence content, user emails, IPs, or case identifiers.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..core import config
from ..core.database import connect


class BigQueryNotConfigured(RuntimeError):
    """Raised when BigQuery is not configured or its dataset is not provisioned."""


_TABLE_NAME = "daily_platform_metrics"
_METRIC_FIELDS = (
    "total_users", "active_users", "total_cases", "open_cases", "closed_cases",
    "total_searches", "completed_searches", "failed_searches", "running_searches", "searches_24h",
    "total_incidents", "open_incidents", "total_evidence", "evidence_24h", "total_feedback", "feedback_24h",
)
_SCHEMA = [
    ("snapshot_date", "DATE", "REQUIRED"),
    ("generated_at", "TIMESTAMP", "REQUIRED"),
    *[(name, "INT64", "REQUIRED") for name in _METRIC_FIELDS],
]


def is_configured() -> bool:
    """Configuration-only check; does not make a cloud request."""
    return bool(config.BIGQUERY_PROJECT and config.BIGQUERY_DATASET)


def status() -> dict[str, Any]:
    return {
        "enabled": is_configured(),
        "dataset": config.BIGQUERY_DATASET if is_configured() else None,
        "location": config.BIGQUERY_LOCATION if is_configured() else None,
        "table": _TABLE_NAME if is_configured() else None,
        "message": "Configured; sync will verify cloud permissions and dataset access."
        if is_configured() else
        "BigQuery is not configured. Set BIGQUERY_PROJECT and BIGQUERY_DATASET to enable warehouse analytics.",
    }


def build_snapshot(now: datetime | None = None) -> dict[str, Any]:
    """Build a count-only snapshot from the operational DB without returning identifying data."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    since = (current - timedelta(hours=24)).isoformat(timespec="seconds")
    with connect() as db:
        row = db.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM users) AS total_users,
              (SELECT COUNT(*) FROM users WHERE status = 'active') AS active_users,
              (SELECT COUNT(*) FROM cases) AS total_cases,
              (SELECT COUNT(*) FROM cases WHERE status != 'closed') AS open_cases,
              (SELECT COUNT(*) FROM cases WHERE status = 'closed') AS closed_cases,
              (SELECT COUNT(*) FROM searches) AS total_searches,
              (SELECT COUNT(*) FROM searches WHERE status = 'completed') AS completed_searches,
              (SELECT COUNT(*) FROM searches WHERE status = 'failed') AS failed_searches,
              (SELECT COUNT(*) FROM searches WHERE status IN ('queued', 'running')) AS running_searches,
              (SELECT COUNT(*) FROM searches WHERE created_at >= ?) AS searches_24h,
              (SELECT COUNT(*) FROM incidents) AS total_incidents,
              (SELECT COUNT(*) FROM incidents WHERE status = 'open') AS open_incidents,
              (SELECT COUNT(*) FROM evidence) AS total_evidence,
              (SELECT COUNT(*) FROM evidence WHERE captured_at >= ?) AS evidence_24h,
              (SELECT COUNT(*) FROM feedback) AS total_feedback,
              (SELECT COUNT(*) FROM feedback WHERE created_at >= ?) AS feedback_24h
            """,
            (since, since, since),
        ).fetchone()

    result: dict[str, Any] = {
        "snapshot_date": current.date(),
        "generated_at": current.replace(microsecond=0),
    }
    result.update({name: int(row[name] or 0) for name in _METRIC_FIELDS})
    return result


def _make_client():
    if not is_configured():
        raise BigQueryNotConfigured("Set BIGQUERY_PROJECT and BIGQUERY_DATASET.")
    from google.cloud import bigquery

    credentials_json = os.getenv("BIGQUERY_CREDENTIALS_JSON", "").strip()
    if credentials_json:
        from google.oauth2 import service_account

        try:
            info = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(info)
        except (ValueError, TypeError, KeyError) as exc:
            raise BigQueryNotConfigured("BIGQUERY_CREDENTIALS_JSON is not valid service-account JSON.") from exc
        return bigquery.Client(project=config.BIGQUERY_PROJECT, credentials=credentials)
    # Supports Application Default Credentials / workload identity on Google Cloud.
    return bigquery.Client(project=config.BIGQUERY_PROJECT)


def _table_id() -> str:
    return f"{config.BIGQUERY_PROJECT}.{config.BIGQUERY_DATASET}.{_TABLE_NAME}"


def _ensure_table(client) -> None:
    from google.cloud import bigquery

    dataset_id = f"{config.BIGQUERY_PROJECT}.{config.BIGQUERY_DATASET}"
    try:
        client.get_dataset(dataset_id)
    except bigquery.NotFound as exc:
        raise BigQueryNotConfigured(
            f"BigQuery dataset {dataset_id} does not exist. Create it in {config.BIGQUERY_LOCATION} first."
        ) from exc

    table_id = _table_id()
    try:
        client.get_table(table_id)
    except bigquery.NotFound:
        schema = [bigquery.SchemaField(name, kind, mode=mode) for name, kind, mode in _SCHEMA]
        table = bigquery.Table(table_id, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field="snapshot_date"
        )
        client.create_table(table, exists_ok=True)


def sync_snapshot(client=None) -> dict[str, Any]:
    """Idempotently upsert today's UTC aggregate snapshot."""
    from google.cloud import bigquery

    client = client or _make_client()
    _ensure_table(client)
    snapshot = build_snapshot()
    columns = ("snapshot_date", "generated_at", *_METRIC_FIELDS)
    params = [
        bigquery.ScalarQueryParameter(
            name,
            "DATE" if name == "snapshot_date" else "TIMESTAMP" if name == "generated_at" else "INT64",
            snapshot[name],
        )
        for name in columns
    ]
    assignments = ", ".join(f"{name} = @{name}" for name in columns if name != "snapshot_date")
    insert_columns = ", ".join(columns)
    insert_values = ", ".join(f"@{name}" for name in columns)
    sql = f"""
        MERGE `{_table_id()}` AS target
        USING (SELECT @snapshot_date AS snapshot_date) AS source
        ON target.snapshot_date = source.snapshot_date
        WHEN MATCHED THEN UPDATE SET {assignments}
        WHEN NOT MATCHED THEN INSERT ({insert_columns}) VALUES ({insert_values})
    """
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in snapshot.items()
    }


def latest_metrics(limit: int = 30, client=None) -> list[dict[str, Any]]:
    """Return recent aggregate snapshots; never query raw operational records."""
    from google.cloud import bigquery

    client = client or _make_client()
    _ensure_table(client)
    safe_limit = max(1, min(int(limit), 90))
    rows = client.query(
        f"SELECT {', '.join(_field[0] for _field in _SCHEMA)} FROM `{_table_id()}` "
        f"ORDER BY snapshot_date DESC LIMIT {safe_limit}",
        job_config=bigquery.QueryJobConfig(use_query_cache=True),
    ).result()
    output = []
    for row in rows:
        item = {name: row[name] for name, _, _ in _SCHEMA}
        output.append({
            key: value.isoformat() if isinstance(value, (date, datetime)) else value
            for key, value in item.items()
        })
    return output
