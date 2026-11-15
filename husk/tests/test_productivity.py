from conftest import API


def test_notes_ordering_put_patch_filters(client):
    green = client.post(f"{API}/notes", json={"title": "low", "color": "green"}).json()
    red = client.post(f"{API}/notes", json={"title": "high", "color": "red"}).json()
    default = client.post(f"{API}/notes", json={"title": "default"}).json()
    assert default["color"] == "yellow"
    assert [n["title"] for n in client.get(f"{API}/notes").json()] == ["high", "default", "low"]  # red > yellow > green
    client.patch(f"{API}/notes/{green['id']}", json={"pinned": True})
    assert client.get(f"{API}/notes").json()[0]["title"] == "low"  # pinned first
    replaced = client.put(f"{API}/notes/{red['id']}", json={"title": "new", "content": "body", "color": "green"}).json()
    assert (replaced["title"], replaced["color"], replaced["pinned"]) == ("new", "green", False)
    assert client.get(f"{API}/notes?q=body").json()[0]["id"] == red["id"]
    assert [n["id"] for n in client.get(f"{API}/notes?color=yellow").json()] == [default["id"]]
    assert client.get(f"{API}/notes/{red['id']}").json()["content"] == "body"
    assert client.patch(f"{API}/notes/{red['id']}", json={"title": None}).status_code == 422
    assert client.patch(f"{API}/notes/{red['id']}", json={"color": "purple"}).status_code == 422
    assert client.delete(f"{API}/notes/{red['id']}").status_code == 204 and client.get(f"{API}/notes/{red['id']}").status_code == 404


def test_tasks_status_transitions_filters(client):
    t = client.post(f"{API}/tasks", json={"task": "Ship", "due_at": "2020-01-01T00:00:00Z"}).json()
    done = client.patch(f"{API}/tasks/{t['id']}/status", json={"status": "done"}).json()
    assert done["status"] == "done" and done["completed_at"] is not None
    reopened = client.patch(f"{API}/tasks/{t['id']}", json={"status": "todo"}).json()
    assert reopened["completed_at"] is None
    assert client.get(f"{API}/tasks?status=todo").json()[0]["id"] == t["id"]
    client.patch(f"{API}/tasks/{t['id']}/status", json={"status": "done"})
    assert client.get(f"{API}/tasks?status=todo").json() == []  # time-based filters (overdue etc.) were removed
    assert client.get(f"{API}/tasks?status=done&q=shi").json()[0]["id"] == t["id"]
    assert client.patch(f"{API}/tasks/{t['id']}", json={"due_at": None}).json()["due_at"] is None  # null clears
    assert client.patch(f"{API}/tasks/{t['id']}", json={"task": "Ship v2"}).json()["task"] == "Ship v2"
    assert client.patch(f"{API}/tasks/{t['id']}", json={"task": None}).status_code == 422
    assert client.patch(f"{API}/tasks/{t['id']}/status", json={"status": "bogus"}).status_code == 422
    assert client.delete(f"{API}/tasks/{t['id']}").status_code == 204


def test_kanban_positions_stay_contiguous(client):
    ids = [client.post(f"{API}/tasks", json={"task": f"T{i}"}).json()["id"] for i in range(3)]
    positions = lambda status: [(t["task"], t["position"]) for t in client.get(f"{API}/tasks?status={status}").json()]
    assert positions("todo") == [("T0", 0), ("T1", 1), ("T2", 2)]
    client.patch(f"{API}/tasks/{ids[0]}/status", json={"status": "done"})  # moved task is appended to the target column
    assert positions("todo") == [("T1", 0), ("T2", 1)] and positions("done") == [("T0", 0)]
    client.patch(f"{API}/tasks/{ids[2]}/status", json={"status": "done", "position": 0})  # explicit insert position
    assert positions("done") == [("T2", 0), ("T0", 1)]
    client.patch(f"{API}/tasks/{ids[0]}", json={"position": 0})  # reorder within a column
    assert positions("done") == [("T0", 0), ("T2", 1)]
    client.delete(f"{API}/tasks/{ids[1]}")
    assert positions("todo") == []
    client.delete(f"{API}/tasks/{ids[0]}")
    assert positions("done") == [("T2", 0)]  # column compacted after delete


def test_calendar_range_overlap_validation_and_calendars(client):
    ok = client.post(f"{API}/calendar/events", json={"title": "Offsite", "start_at": "2026-10-20T10:00:00Z", "end_at": "2026-10-22T10:00:00Z"})
    assert ok.status_code == 201 and ok.json()["source"] == "local" and ok.json()["read_only"] is False
    assert client.post(f"{API}/calendar/events", json={"title": "Bad", "start_at": "2026-10-20T11:00:00Z", "end_at": "2026-10-20T10:00:00Z"}).status_code == 422
    # an event that started before the window but overlaps it must be returned
    hits = client.get(f"{API}/calendar/events?start=2026-10-21T00:00:00Z&end=2026-10-23T00:00:00Z").json()
    assert [e["title"] for e in hits] == ["Offsite"]
    assert client.get(f"{API}/calendar/events?start=2026-10-23T00:00:00Z").json() == []
    eid = ok.json()["id"]
    assert client.patch(f"{API}/calendar/events/{eid}", json={"end_at": "2026-10-19T00:00:00Z"}).status_code == 422
    cals = client.get(f"{API}/calendar/calendars").json()
    assert len(cals) == 1 and cals[0]["provider"] == "local"
    assert client.delete(f"{API}/calendar/events/{eid}").status_code == 204
    assert client.post(f"{API}/calendar/sync").json()["synced"] == []  # calendar is local-only


def test_synced_events_are_read_only(client, db):
    from assistant.db.models import CalendarEvent
    from assistant.core.timeutil import utcnow
    event = CalendarEvent(title="Remote", start_at=utcnow(), source="google", external_id="x")
    db.add(event); db.commit()
    assert client.patch(f"{API}/calendar/events/{event.id}", json={"title": "x"}).status_code == 409
    assert client.delete(f"{API}/calendar/events/{event.id}").status_code == 409
