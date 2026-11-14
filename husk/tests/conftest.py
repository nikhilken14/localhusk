"""Test environment: throw-away SQLite file, in-memory keyring, no background workers.

Environment variables must be set before ``assistant`` is imported (settings and the DB engine are
created at import time).
"""
import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="husk-tests-")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{Path(_TMP, 'test.db').as_posix()}",
    "ENABLE_WORKERS": "false", "AUTO_MIGRATE": "false", "LOG_LEVEL": "WARNING",
    "ALLOWED_HOSTS": "testserver,127.0.0.1,localhost", "CORS_ORIGINS": "http://localhost:5173",
    "GOOGLE_CLIENT_ID": "test-google-id", "GOOGLE_CLIENT_SECRET": "test-google-secret", "MICROSOFT_CLIENT_ID": "",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import keyring  # noqa: E402
import keyring.errors  # noqa: E402
import pytest  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.store[(service, username)]


keyring.set_keyring(MemoryKeyring())

from fastapi.testclient import TestClient  # noqa: E402

from assistant.db.base import Base  # noqa: E402
from assistant.db.engine import engine  # noqa: E402
from assistant.db.session import SessionLocal  # noqa: E402
from assistant.main import create_app  # noqa: E402
from assistant.providers.base import Completion, StreamChunk, Usage  # noqa: E402
from assistant.providers.registry import registry  # noqa: E402

API = "/api/v1"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture()
def client():
    return TestClient(create_app())


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


class FakeAdapter:
    def __init__(self, reply="Hello there", fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    async def complete(self, messages, options, api_key, base_url=None):
        self.calls.append(list(messages))
        if self.fail:
            raise RuntimeError("boom with key sk-secretsecretsecret")
        return Completion(self.reply, Usage(10, 4))

    async def stream(self, messages, options, api_key, base_url=None):
        self.calls.append(list(messages))
        if self.fail:
            raise RuntimeError("stream boom")
        for part in ("Hel", "lo"):
            yield StreamChunk(delta=part)
        yield StreamChunk(usage=Usage(10, 2))


@pytest.fixture()
def fake_llm(monkeypatch):
    adapter = FakeAdapter()
    for kind in list(registry._providers):
        monkeypatch.setitem(registry._providers, kind, adapter)
    return adapter


@pytest.fixture()
def model_id(client):
    r = client.post(f"{API}/llm/models", json={"name": "Test", "kind": "openai", "model": "gpt-test", "api_key": "sk-testtesttest"})
    assert r.status_code == 201, r.text
    return r.json()["id"]
