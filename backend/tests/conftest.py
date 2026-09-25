import os
import tempfile

# Must be set before app modules are imported.
os.environ["MOCK_MODE"] = "1"
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["RATE_LIMIT_PER_HOUR"] = "1000"
os.environ["JOBS_INLINE"] = "1"  # run searches synchronously inside the request
os.environ["JWT_SECRET"] = "test-secret-not-for-production-0123456789"
os.environ["ALERT_SEARCHES_PER_5MIN"] = "1000"
os.environ["ALERT_DISTINCT_TARGETS_PER_HOUR"] = "1000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN = {"email": "admin@test.local", "password": "admin-pass-123"}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_h(client):
    r = client.post("/api/auth/setup", json=ADMIN)
    assert r.status_code == 201, r.text
    assert r.json()["user"]["role"] == "super_admin"
    return bearer(r.json()["access_token"])


def make_user(client, admin_h, role: str, name: str | None = None) -> dict:
    cred = {"email": f"{name or role}@test.local", "password": f"{name or role}-pass-123"}
    r = client.post("/api/users", json={**cred, "role": role}, headers=admin_h)
    assert r.status_code == 201, r.text
    return bearer(client.post("/api/auth/login", json=cred).json()["access_token"])


@pytest.fixture(scope="session")
def analyst_h(client, admin_h):
    return make_user(client, admin_h, "analyst")


@pytest.fixture(scope="session")
def investigator_h(client, admin_h):
    return make_user(client, admin_h, "investigator")


@pytest.fixture(scope="session")
def user_h(client, admin_h):
    return make_user(client, admin_h, "user")


@pytest.fixture(scope="session")
def auditor_h(client, admin_h):
    return make_user(client, admin_h, "auditor")


@pytest.fixture(scope="session")
def secadmin_h(client, admin_h):
    return make_user(client, admin_h, "security_admin")
