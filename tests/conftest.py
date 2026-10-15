"""Test setup: isolated SQLite file per test module, offline weather, no real LLM calls."""
import os

# Must run before the app imports config (real env vars win over .env).
os.environ["WEATHER_PROVIDER"] = "clearsky"
os.environ["D360_AI_API_KEY"] = ""
os.environ["NOTIFY_WEBHOOK_URL"] = ""
os.environ["SECRET_KEY"] = "test-secret"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["DATABASE_PATH"] = str(tmp_path_factory.mktemp("db") / "test.db")
    from app.main import app

    with TestClient(app) as c:  # lifespan creates schema + seeds sample data
        yield c


def _login(client, email, password):
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture(scope="module")
def engineer(client):
    return _login(client, "engineer@solarclear.local", "Engineer@123")


@pytest.fixture(scope="module")
def admin(client):
    return _login(client, "admin@solarclear.local", "Admin@123")


@pytest.fixture
def db():
    from app.database import connect

    conn = connect()
    yield conn
    conn.commit()
    conn.close()


def dtr_id(client, headers, code):
    return next(d["id"] for d in client.get("/api/dtrs", headers=headers).json() if d["code"] == code)
