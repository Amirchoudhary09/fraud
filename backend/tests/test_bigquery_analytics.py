from datetime import datetime, timezone

from app.core import config
from app.services import bigquery_analytics


def test_snapshot_contains_only_aggregate_fields(client, admin_h):
    # Create representative data through the application so this exercises the real operational DB.
    response = client.get("/api/admin/dashboard", headers=admin_h)
    assert response.status_code == 200

    snapshot = bigquery_analytics.build_snapshot(datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc))
    expected = {
        "snapshot_date", "generated_at", "total_users", "active_users", "total_cases", "open_cases",
        "closed_cases", "total_searches", "completed_searches", "failed_searches", "running_searches",
        "searches_24h", "total_incidents", "open_incidents", "total_evidence", "evidence_24h",
        "total_feedback", "feedback_24h",
    }
    assert set(snapshot) == expected
    assert snapshot["snapshot_date"].isoformat() == "2026-10-12"
    assert all(isinstance(snapshot[name], int) and snapshot[name] >= 0
               for name in expected if name not in {"snapshot_date", "generated_at"})
    serialized = repr(snapshot).lower()
    assert "admin@test.local" not in serialized
    assert "normalized_query" not in serialized
    assert "content_hash" not in serialized


def test_warehouse_status_reports_unconfigured(client, admin_h, monkeypatch):
    monkeypatch.setattr(config, "BIGQUERY_PROJECT", "")
    monkeypatch.setattr(config, "BIGQUERY_DATASET", "fraud_analytics")
    response = client.get("/api/admin/warehouse/status", headers=admin_h)
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_warehouse_metrics_is_empty_when_unconfigured(client, admin_h, monkeypatch):
    monkeypatch.setattr(config, "BIGQUERY_PROJECT", "")
    monkeypatch.setattr(config, "BIGQUERY_DATASET", "fraud_analytics")
    response = client.get("/api/admin/warehouse/metrics", headers=admin_h)
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["rows"] == []


def test_warehouse_sync_requires_configuration(client, admin_h, monkeypatch):
    monkeypatch.setattr(config, "BIGQUERY_PROJECT", "")
    monkeypatch.setattr(config, "BIGQUERY_DATASET", "fraud_analytics")
    response = client.post("/api/admin/warehouse/sync", headers=admin_h)
    assert response.status_code == 503


def test_warehouse_endpoints_require_permissions(client, analyst_h, user_h):
    status = client.get("/api/admin/warehouse/status", headers=analyst_h)
    sync = client.post("/api/admin/warehouse/sync", headers=user_h)
    assert status.status_code == 403
    assert sync.status_code == 403
