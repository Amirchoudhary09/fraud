import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # backend/
load_dotenv(ROOT / ".env")

# Frontend origins allowed to call the API (comma-separated), e.g. the Railway frontend URL.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if o.strip()]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001").strip()
# On Railway, mount a volume and set DATA_DIR to its path so data survives redeploys.
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "app.db")))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads")))
CALIBRATION_PATH = Path(os.getenv("CALIBRATION_PATH", str(DATA_DIR / "calibration.json")))

# Mock mode is used automatically when no key is configured, or can be forced.
MOCK_MODE = os.getenv("MOCK_MODE", "").lower() in ("1", "true", "yes") or not GEMINI_API_KEY

MAX_QUERIES = int(os.getenv("MAX_QUERIES", "4"))
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "30"))

# Hybrid matching: the LLM judge costs one extra model call per candidate.
LLM_JUDGE = os.getenv("LLM_JUDGE", "1").lower() in ("1", "true", "yes")
MAX_JUDGED_CANDIDATES = int(os.getenv("MAX_JUDGED_CANDIDATES", "5"))

# Auth. Secrets come from the environment (Railway variables / a cloud secrets manager).
# If JWT_SECRET / EVIDENCE_KEY are unset, random ones are generated into DATA_DIR (dev only).
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
# Roles that must enrol MFA before they can use the API (comma-separated, empty = optional for all).
MFA_REQUIRED_ROLES = [r.strip() for r in os.getenv("MFA_REQUIRED_ROLES", "").split(",") if r.strip()]

# Evidence encryption at rest (Fernet key, 32 url-safe base64 bytes). Use a KMS-managed key in production.
EVIDENCE_KEY = os.getenv("EVIDENCE_KEY", "").strip()

# Audit log lives in its own database file, plus an append-only JSONL mirror (ship it to WORM storage).
AUDIT_DB_PATH = Path(os.getenv("AUDIT_DB_PATH", str(DATA_DIR / "audit.db")))
AUDIT_MIRROR_PATH = Path(os.getenv("AUDIT_MIRROR_PATH", str(DATA_DIR / "audit.jsonl")))
# Client IPs are only stored as salted hashes.
IP_HASH_SALT = os.getenv("IP_HASH_SALT", "change-me")

MAX_BODY_MB = int(os.getenv("MAX_BODY_MB", "12"))
BREAK_GLASS_HOURS = int(os.getenv("BREAK_GLASS_HOURS", "4"))

# Security monitoring thresholds.
ALERT_SEARCHES_PER_5MIN = int(os.getenv("ALERT_SEARCHES_PER_5MIN", "20"))
ALERT_DISTINCT_TARGETS_PER_HOUR = int(os.getenv("ALERT_DISTINCT_TARGETS_PER_HOUR", "15"))
ALERT_FAILED_LOGINS_PER_15MIN = int(os.getenv("ALERT_FAILED_LOGINS_PER_15MIN", "5"))
ALERT_EXPORTS_PER_HOUR = int(os.getenv("ALERT_EXPORTS_PER_HOUR", "20"))
ALERT_AUTHZ_DENIED_PER_15MIN = int(os.getenv("ALERT_AUTHZ_DENIED_PER_15MIN", "10"))

# Safe fetch: only these URL schemes/ports, response size and time limits.
FETCH_MAX_BYTES = int(os.getenv("FETCH_MAX_BYTES", str(2 * 1024 * 1024)))
FETCH_TIMEOUT = float(os.getenv("FETCH_TIMEOUT", "10"))
# Optional comma-separated domain denylist for evidence capture.
FETCH_DENY_DOMAINS = [d.strip().lower() for d in os.getenv("FETCH_DENY_DOMAINS", "").split(",") if d.strip()]

# Data retention: cases/searches older than this are purged at startup (0 = keep forever).
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))

# Calibrated confidence is only shown once this many reviewed labels were used to fit it.
MIN_CALIBRATION_LABELS = int(os.getenv("MIN_CALIBRATION_LABELS", "30"))

# Audit export (optional). Events are shipped from a cursor every EXPORT_INTERVAL seconds.
EXPORT_INTERVAL = int(os.getenv("EXPORT_INTERVAL", "30"))
SIEM_WEBHOOK_URL = os.getenv("SIEM_WEBHOOK_URL", "").strip()          # e.g. https://splunk:8088/services/collector
SIEM_FORMAT = os.getenv("SIEM_FORMAT", "json").strip()                # json | splunk_hec
SIEM_AUTH_HEADER = os.getenv("SIEM_AUTH_HEADER", "").strip()          # e.g. "Splunk <token>"
WORM_S3_BUCKET = os.getenv("WORM_S3_BUCKET", "").strip()              # bucket created WITH Object Lock
WORM_S3_PREFIX = os.getenv("WORM_S3_PREFIX", "audit/").strip()
WORM_S3_ENDPOINT = os.getenv("WORM_S3_ENDPOINT", "").strip()          # empty = AWS; or MinIO/B2 endpoint
WORM_S3_REGION = os.getenv("WORM_S3_REGION", "").strip()
WORM_RETENTION_DAYS = int(os.getenv("WORM_RETENTION_DAYS", "2555"))   # ~7 years

# Redis (optional): shared rate limits and a reliable job queue for multiple API replicas.
# When set, run `python -m app.workers.worker` as a separate service to execute jobs.
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# Job queue: number of worker threads; JOBS_INLINE=1 runs jobs synchronously (tests).
WORKERS = int(os.getenv("WORKERS", "2"))
JOBS_INLINE = os.getenv("JOBS_INLINE", "").lower() in ("1", "true", "yes")
