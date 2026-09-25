import os
import tempfile

# Must be set before app modules are imported.
os.environ["MOCK_MODE"] = "1"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["RATE_LIMIT_PER_HOUR"] = "1000"
