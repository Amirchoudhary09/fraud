import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
DB_PATH = Path(os.getenv("DB_PATH", str(ROOT / "data" / "app.db")))

# Mock mode is used automatically when no key is configured, or can be forced.
MOCK_MODE = os.getenv("MOCK_MODE", "").lower() in ("1", "true", "yes") or not GEMINI_API_KEY

MAX_QUERIES = int(os.getenv("MAX_QUERIES", "4"))
RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "30"))
