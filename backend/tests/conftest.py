"""Test fixtures. Environment is configured BEFORE the app is imported so tests use a
throw-away SQLite DB and model folder (your real data is never touched)."""
import os
import tempfile
import warnings

warnings.filterwarnings("ignore")
_tmp = tempfile.mkdtemp(prefix="sro_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["MODEL_DIR"] = os.path.join(_tmp, "models")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["AUTO_TRAIN"] = "false"
os.environ["SEED_HISTORY_HOURS"] = "24"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-use-0123456789"
os.environ["ADMIN_PASSWORD"] = "Test-Admin-Pass-1"
os.environ["PASSWORD_HASH_ITERATIONS"] = "1000"      # fast hashing for tests only
os.environ["INGEST_API_KEY"] = "test-ingest-key"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ml.registry import model_service  # noqa: E402


@pytest.fixture(scope="session")
def trained_model():
    """Train a small model once (a few seconds) and share it across tests."""
    model_service.train(n_samples=3000, seed=1)
    return model_service


ADMIN = ("admin", "Test-Admin-Pass-1")


@pytest.fixture(scope="session")
def client(trained_model):
    """An *authenticated admin* client (the real startup runs: seed, load model, backfill, create admin)."""
    from app.main import app

    with TestClient(app) as c:
        r = c.post("/auth/login", data={"username": ADMIN[0], "password": ADMIN[1]})
        assert r.status_code == 200, r.text
        c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}"})
        yield c


@pytest.fixture(scope="session")
def anon(client):
    """A client with no credentials at all (same running app)."""
    from app.main import app

    return TestClient(app)


def login(anon_client, username, password):
    return anon_client.post("/auth/login", data={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}
