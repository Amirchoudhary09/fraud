"""WORM export: audit events to S3-compatible object storage with Object Lock.

Each batch becomes one immutable JSONL object:
  {prefix}{first_seq:012d}-{last_seq:012d}.jsonl
written with ObjectLockMode=COMPLIANCE (nobody, including the bucket owner, can delete or
overwrite it before the retain-until date) and a SHA-256 checksum. Object metadata carries
the chain hash of the last event, so a verifier can link segments together.

The bucket must be created with Object Lock enabled. Works with AWS S3, Cloudflare R2
(without Object Lock, so use S3/MinIO for real WORM), Backblaze B2 and MinIO.
"""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

from ...core import config


class WormExporter:
    name = "worm"
    batch_size = 1000

    def __init__(self, client=None):
        self._client = client

    def enabled(self) -> bool:
        return bool(config.WORM_S3_BUCKET)

    def describe(self) -> str | None:
        return f"s3://{config.WORM_S3_BUCKET}/{config.WORM_S3_PREFIX} ({config.WORM_RETENTION_DAYS} days, COMPLIANCE)" \
            if self.enabled() else None

    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("s3", endpoint_url=config.WORM_S3_ENDPOINT or None,
                                        region_name=config.WORM_S3_REGION or None)
        return self._client

    @staticmethod
    def key(events: list[dict]) -> str:
        return f"{config.WORM_S3_PREFIX}{events[0]['seq']:012d}-{events[-1]['seq']:012d}.jsonl"

    def ship(self, events: list[dict]) -> None:
        body = ("\n".join(json.dumps(e, sort_keys=True) for e in events) + "\n").encode()
        retain = datetime.now(timezone.utc) + timedelta(days=config.WORM_RETENTION_DAYS)
        self.client().put_object(
            Bucket=config.WORM_S3_BUCKET,
            Key=self.key(events),
            Body=body,
            ContentType="application/x-ndjson",
            ChecksumSHA256=base64.b64encode(hashlib.sha256(body).digest()).decode(),
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain,
            Metadata={"first-seq": str(events[0]["seq"]), "last-seq": str(events[-1]["seq"]),
                      "last-hash": events[-1]["hash"], "prev-hash": events[0]["prev_hash"]},
        )
