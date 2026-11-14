import json

from assistant.db.models import ChatMessage, Conversation
from conftest import API


def _conv(client, title="New chat"):
    r = client.post(f"{API}/conversations", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_conversation_crud_search_pagination(client):
    ids = [_conv(client, f"Chat {i}") for i in range(3)]
    page = client.get(f"{API}/conversations?limit=2").json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["limit"] == 2
    assert client.get(f"{API}/conversations?q=Chat 1").json()["total"] == 1
    assert client.get(f"{API}/conversations?q=%25").json()["total"] == 0  # wildcard is escaped, not a match-all
    renamed = client.patch(f"{API}/conversations/{ids[0]}", json={"title": "Renamed", "pinned": True}).json()
    assert renamed["title"] == "Renamed" and renamed["pinned"] is True
    assert client.get(f"{API}/conversations").json()["items"][0]["id"] == ids[0]  # pinned first
    assert client.patch(f"{API}/conversations/{ids[0]}", json={"title": None}).status_code == 422
    assert client.delete(f"{API}/conversations/{ids[0]}").status_code == 204
    assert client.get(f"{API}/conversations/{ids[0]}").status_code == 404


def test_send_message_persists_both_sides_records_usage_and_autotitles(client, fake_llm, model_id):
    cid = _conv(client)
    r = client.post(f"{API}/conversations/{cid}/messages", json={"content": "What is the capital of France?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assistant_message"]["content"] == "Hello there" and body["usage"] == {"input_tokens": 10, "output_tokens": 4, "estimated": False}
    messages = client.get(f"{API}/conversations/{cid}/messages").json()
    assert [m["role"] for m in messages["items"]] == ["user", "assistant"] and messages["total"] == 2
    assert client.get(f"{API}/conversations/{cid}").json()["title"].startswith("What is the capital")
    assert client.get(f"{API}/usage/today").json()["total_tokens"] == 14
    desc = client.get(f"{API}/conversations/{cid}/messages?order=desc&limit=1").json()
    assert desc["items"][0]["role"] == "assistant" and desc["total"] == 2


def test_llm_failure_is_502_without_leaking_the_key(client, fake_llm, model_id):
    fake_llm.fail = True
    cid = _conv(client)
    r = client.post(f"{API}/conversations/{cid}/messages", json={"content": "hi"})
    assert r.status_code == 502 and "sk-secretsecretsecret" not in r.text and r.json()["code"] == "llm_error"


def test_no_model_configured_is_400(client):
    cid = _conv(client)
    r = client.post(f"{API}/conversations/{cid}/messages", json={"content": "hi"})
    assert r.status_code == 400 and r.json()["code"] == "no_default_model"


def test_stream_emits_events_and_saves_message(client, fake_llm, model_id):
    cid = _conv(client)
    with client.stream("POST", f"{API}/conversations/{cid}/stream", json={"content": "hi"}) as response:
        events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["start", "delta", "delta", "usage", "done"]
    assert "".join(e["delta"] for e in events if e["type"] == "delta") == "Hello"
    stored = client.get(f"{API}/conversations/{cid}/messages").json()["items"]
    assert stored[-1]["content"] == "Hello" and stored[-1]["status"] == "complete"


def test_stream_error_event(client, fake_llm, model_id):
    fake_llm.fail = True
    cid = _conv(client)
    with client.stream("POST", f"{API}/conversations/{cid}/stream", json={"content": "hi"}) as response:
        events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    assert events[-1]["type"] == "error"


def test_delete_conversation_cascades_messages(client, fake_llm, model_id, db):
    cid = _conv(client)
    client.post(f"{API}/conversations/{cid}/messages", json={"content": "hi"})
    client.delete(f"{API}/conversations/{cid}")
    assert db.query(ChatMessage).count() == 0  # needs PRAGMA foreign_keys=ON / ORM cascade


def test_history_window_search_and_no_deletion(client, db):
    from datetime import timedelta
    from assistant.core.timeutil import utcnow
    old, recent = Conversation(title="Old chat", updated_at=utcnow() - timedelta(days=9)), Conversation(title="Recent chat")
    db.add_all([old, recent]); db.flush()
    db.add(ChatMessage(conversation_id=old.id, role="user", content="the quarterly budget review"))
    db.commit()
    default = client.get(f"{API}/history").json()
    assert [i["title"] for i in default["items"]] == ["Recent chat"]  # five-day default window
    assert client.get(f"{API}/history?all=true").json()["total"] == 2
    hit = client.get(f"{API}/history?all=true&q=budget").json()
    assert hit["total"] == 1 and "budget" in hit["items"][0]["matches"][0]["snippet"]
    assert db.query(Conversation).count() == 2  # reading history never deletes anything
    assert client.post(f"{API}/history/prune?days=5").json() == {"deleted_conversations": 1}
