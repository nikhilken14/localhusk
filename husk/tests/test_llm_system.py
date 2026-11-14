from assistant.core.timeutil import utcnow
from conftest import API


def test_model_lifecycle_default_key_preservation_and_test(client, fake_llm, monkeypatch):
    first = client.post(f"{API}/llm/models", json={"name": "A", "kind": "openai", "model": "m1", "api_key": "sk-aaaaaaaaaa"}).json()
    assert first["is_default"] is True and first["has_api_key"] is True and "api_key" not in first
    second = client.post(f"{API}/llm/models", json={"name": "B", "kind": "ollama", "model": "llama"}).json()
    assert second["is_default"] is False and second["has_api_key"] is False
    assert client.post(f"{API}/llm/models/{second['id']}/default").json()["is_default"] is True
    models = {m["id"]: m for m in client.get(f"{API}/llm/models").json()}
    assert models[first["id"]]["is_default"] is False
    updated = client.put(f"{API}/llm/models/{first['id']}", json={"name": "A2", "kind": "openai", "model": "m1", "api_key": ""}).json()
    assert updated["name"] == "A2" and updated["has_api_key"] is True  # empty key preserves the stored one
    result = client.post(f"{API}/llm/models/{first['id']}/test").json()
    assert result["ok"] is True and result["latency_ms"] is not None
    assert client.get(f"{API}/usage/today").json()["default_model"]["id"] == second["id"]
    fake_llm.fail = True
    failed = client.post(f"{API}/llm/models/{first['id']}/test").json()
    assert failed["ok"] is False and "sk-secretsecretsecret" not in failed["error"]
    assert client.delete(f"{API}/llm/models/{second['id']}").status_code == 204
    assert client.get(f"{API}/llm/models").json()[0]["is_default"] is True  # default is promoted
    assert client.post(f"{API}/llm/models", json={"name": "X", "kind": "nope", "model": "m"}).status_code == 422


def test_discover_uses_stored_key(client, monkeypatch):
    seen = {}

    async def fake(kind, base_url, api_key):
        seen.update(kind=kind, key=api_key)
        return [{"id": "gpt-x", "name": "gpt-x"}]

    monkeypatch.setattr("assistant.api.v1.llm.discover_models", fake)
    created = client.post(f"{API}/llm/models", json={"name": "A", "kind": "openai", "model": "m", "api_key": "sk-stored-key-123"}).json()
    r = client.post(f"{API}/llm/discover", json={"kind": "openai", "model_id": created["id"]})
    assert r.json()["models"][0]["id"] == "gpt-x" and seen["key"] == "sk-stored-key-123"


def test_logs_filtering_and_clear(client, db):
    from assistant.db.models import AppLog
    db.add_all([AppLog(level="INFO", category="agent", message="agent started"), AppLog(level="ERROR", category="mail", message="mail failed")])
    db.commit()
    assert client.get(f"{API}/logs").json()["total"] == 2
    assert client.get(f"{API}/logs?category=mail").json()["items"][0]["message"] == "mail failed"
    assert client.get(f"{API}/logs?level=ERROR").json()["total"] == 1
    assert client.get(f"{API}/logs?q=started").json()["total"] == 1
    assert client.delete(f"{API}/logs").json() == {"deleted": 2}


def test_health_and_request_guards(client):
    assert client.get(f"{API}/health").json()["status"] == "ok"
    ready = client.get(f"{API}/health/ready")
    assert "checks" in ready.json()
    assert client.get(f"{API}/health").headers["x-request-id"]
    assert client.get(f"{API}/health", headers={"Host": "evil.example"}).status_code == 403  # DNS-rebinding guard
    assert client.post(f"{API}/notes", json={"title": "x"}, headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.post(f"{API}/notes", json={"title": "x"}, headers={"Origin": "http://localhost:5173"}).status_code == 201
    assert client.get(f"{API}/nothing-here").json()["code"] == "not_found"


def test_usage_summary(client, db):
    from assistant.db.models import UsageRecord
    db.add_all([UsageRecord(provider_name="A", model="m1", input_tokens=5, output_tokens=7),
                UsageRecord(provider_name="A", model="m2", input_tokens=1, output_tokens=1)]); db.commit()
    rows = client.get(f"{API}/usage/summary?group_by=model").json()["rows"]
    assert {r["key"]: r["total_tokens"] for r in rows} == {"m1": 12, "m2": 2}
    assert client.get(f"{API}/usage/today?since=2000-01-01T00:00:00Z").json()["requests"] == 2
