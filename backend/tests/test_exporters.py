import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import boto3
import pytest
from botocore.stub import ANY, Stubber

from app.core import audit_store, config
from app.repositories import kv
from app.services import exporters
from app.services.exporters.siem import SiemExporter
from app.services.exporters.worm import WormExporter


class _Sink(BaseHTTPRequestHandler):
    received: list = []
    status = 200

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Sink.received.append({"auth": self.headers.get("Authorization"), "body": body.decode()})
        self.send_response(_Sink.status)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def siem(monkeypatch, client, admin_h):
    server = HTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Sink.received, _Sink.status = [], 200
    monkeypatch.setattr(config, "SIEM_WEBHOOK_URL", f"http://127.0.0.1:{server.server_port}/ingest")
    monkeypatch.setattr(config, "SIEM_AUTH_HEADER", "Splunk test-token")
    kv.set("export:siem:cursor", 0)
    yield _Sink
    server.shutdown()


def test_siem_ships_every_event_once(siem, monkeypatch):
    head = audit_store.head_seq()
    assert exporters.run_once(SiemExporter()) == head
    shipped = [e for r in siem.received for e in json.loads(r["body"])["events"]]
    assert [e["seq"] for e in shipped] == list(range(1, head + 1))  # in order, none skipped
    assert all(r["auth"] == "Splunk test-token" for r in siem.received)
    assert {"event_id", "hash", "prev_hash", "event_type"} <= set(shipped[0])
    assert kv.get("export:siem:cursor") == head
    assert exporters.run_once(SiemExporter()) == 0  # nothing new


def test_siem_failure_keeps_cursor(siem):
    audit_store.append("TEST_EVENT")
    before = kv.get("export:siem:cursor")
    siem.status = 503
    assert exporters.run_once(SiemExporter()) == 0
    assert kv.get("export:siem:cursor") == before
    assert "503" in kv.get("export:siem:status")["last_error"]
    siem.status = 200  # destination recovers: the same events are delivered
    assert exporters.run_once(SiemExporter()) >= 1


def test_splunk_hec_format(monkeypatch):
    monkeypatch.setattr(config, "SIEM_FORMAT", "splunk_hec")
    audit_store.append("TEST_EVENT")
    events = audit_store.after(0, 3)
    body, _ = SiemExporter().payload(events)
    lines = [json.loads(line) for line in body.decode().splitlines()]
    assert len(lines) == len(events) and all(line["sourcetype"] == "ie:audit" and "event" in line for line in lines)


def test_worm_writes_compliance_locked_segments(monkeypatch, client, admin_h):
    monkeypatch.setattr(config, "WORM_S3_BUCKET", "audit-worm")
    s3 = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    kv.set("export:worm:cursor", 0)
    events = audit_store.after(0, 1000)
    with Stubber(s3) as stub:
        stub.add_response("put_object", {"ETag": '"x"'}, {
            "Bucket": "audit-worm", "Key": f"audit/{events[0]['seq']:012d}-{events[-1]['seq']:012d}.jsonl",
            "Body": ANY, "ContentType": "application/x-ndjson", "ChecksumSHA256": ANY,
            "ObjectLockMode": "COMPLIANCE", "ObjectLockRetainUntilDate": ANY,
            "Metadata": {"first-seq": "1", "last-seq": str(events[-1]["seq"]), "last-hash": events[-1]["hash"],
                         "prev-hash": audit_store.GENESIS},
        })
        assert exporters.run_once(WormExporter(client=s3), max_batches=1) == len(events)
        stub.assert_no_pending_responses()
    assert kv.get("export:worm:cursor") == events[-1]["seq"]


def test_export_status_endpoint(client, auditor_h, admin_h):
    rows = {r["name"]: r for r in client.get("/api/admin/exports", headers=auditor_h).json()}
    assert set(rows) == {"siem", "worm"} and rows["siem"]["enabled"] is False
    assert client.post("/api/admin/exports/run", headers=auditor_h).status_code == 403


@pytest.mark.skipif(not __import__("os").getenv("TEST_S3_ENDPOINT"), reason="needs an S3/MinIO endpoint (CI)")
def test_worm_segment_cannot_be_deleted_on_real_object_lock_storage(monkeypatch, client, admin_h):
    import os

    from botocore.exceptions import ClientError
    endpoint = os.environ["TEST_S3_ENDPOINT"]
    s3 = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1")
    bucket = "audit-worm-ci"
    try:
        s3.create_bucket(Bucket=bucket, ObjectLockEnabledForBucket=True)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise
    monkeypatch.setattr(config, "WORM_S3_BUCKET", bucket)
    monkeypatch.setattr(config, "WORM_RETENTION_DAYS", 1)
    kv.set("export:worm:cursor", 0)
    assert exporters.run_once(WormExporter(client=s3), max_batches=1) > 0

    key = s3.list_objects_v2(Bucket=bucket)["Contents"][0]["Key"]
    head = s3.head_object(Bucket=bucket, Key=key)
    assert head["ObjectLockMode"] == "COMPLIANCE"
    lines = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode().splitlines()
    assert json.loads(lines[0])["seq"] == 1
    with pytest.raises(ClientError):  # WORM: even the owner cannot delete the locked version
        s3.delete_object(Bucket=bucket, Key=key, VersionId=head["VersionId"])
