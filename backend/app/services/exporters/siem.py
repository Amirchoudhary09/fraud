"""SIEM export over HTTPS.

SIEM_FORMAT=json        POST {"source": "...", "events": [...]}        (generic webhook, Elastic ingest pipeline, etc.)
SIEM_FORMAT=splunk_hec  POST newline-delimited {"time", "sourcetype", "event"} to Splunk HTTP Event Collector
SIEM_AUTH_HEADER is sent as the Authorization header, e.g. "Splunk <token>" or "ApiKey <key>".
Each event keeps its event_id and hash, so the SIEM can de-duplicate and re-verify the chain.
"""
import json
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from ...core import config

SOURCE = "identity-evidence-platform"


class SiemExporter:
    name = "siem"
    batch_size = 200

    def enabled(self) -> bool:
        return bool(config.SIEM_WEBHOOK_URL)

    def describe(self) -> str | None:
        if not self.enabled():
            return None
        u = urlsplit(config.SIEM_WEBHOOK_URL)
        return f"{config.SIEM_FORMAT} → {u.scheme}://{u.netloc}{u.path}"  # never expose tokens in the UI

    def payload(self, events: list[dict]) -> tuple[bytes, str]:
        if config.SIEM_FORMAT == "splunk_hec":
            lines = [json.dumps({"time": datetime.fromisoformat(e["ts"]).timestamp(), "source": SOURCE,
                                 "sourcetype": "ie:audit", "event": e}) for e in events]
            return "\n".join(lines).encode(), "application/json"
        return json.dumps({"source": SOURCE, "events": events}).encode(), "application/json"

    def ship(self, events: list[dict]) -> None:
        body, ctype = self.payload(events)
        headers = {"Content-Type": ctype}
        if config.SIEM_AUTH_HEADER:
            headers["Authorization"] = config.SIEM_AUTH_HEADER
        resp = httpx.post(config.SIEM_WEBHOOK_URL, content=body, headers=headers, timeout=15)
        if resp.status_code >= 300:
            raise RuntimeError(f"SIEM returned HTTP {resp.status_code}")
