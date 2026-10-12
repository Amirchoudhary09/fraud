"""One-shot entry point for a daily Render/Railway cron service.

Run from the backend directory with the same operational database and BigQuery environment as the
API service: `python -m app.analytics_sync`. Output contains aggregate counts only.
"""
import json
import logging
import sys

from .services.bigquery_analytics import BigQueryNotConfigured, sync_snapshot

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    try:
        snapshot = sync_snapshot()
    except BigQueryNotConfigured as exc:
        logging.error("BigQuery analytics is not ready: %s", exc)
        return 2
    except Exception:
        logging.exception("BigQuery analytics sync failed")
        return 1
    print(json.dumps({"ok": True, "snapshot": snapshot}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
