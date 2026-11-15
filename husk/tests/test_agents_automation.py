import json
from datetime import timedelta

from assistant.db.models import AgentRun, AutomationJob, Note, Task
from assistant.services import automation as auto
from assistant.services.agent_runtime import worker
from conftest import API


def _agent(client, tools=("notes.list", "tasks.create"), **extra):
    r = client.post(f"{API}/agents", json={"name": "Helper", "tools": list(tools), **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _drain():
    """Run the worker synchronously until the queue is empty (no LLM planning needed: plans are supplied)."""
    while (run_id := worker.claim_next_run()):
        worker.execute_run(run_id)


def test_catalog_and_agent_validation(client, model_id):
    catalog = client.get(f"{API}/agents/catalog").json()
    assert {"notes.list", "tasks.create", "calendar.create"} <= {t["id"] for t in catalog["tools"]}
    assert catalog["models"][0]["id"] == model_id
    assert client.post(f"{API}/agents", json={"name": "x", "tools": ["shell.exec"]}).status_code == 422
    assert client.post(f"{API}/agents", json={"name": "x", "provider_id": "nope"}).status_code == 404
    assert client.get(f"{API}/tools/notes.list").json()["permission"]["requires_approval"] is False
    assert client.get(f"{API}/tools/tasks.create").json()["permission"]["requires_approval"] is True
    assert client.get(f"{API}/tools/nope").status_code == 404


def test_read_only_run_completes_with_events(client, db):
    db.add(Note(title="hello")); db.commit()
    aid = _agent(client)
    run = client.post(f"{API}/agents/{aid}/run", json={"input": "list notes", "plan": {"steps": [{"tool": "notes.list", "arguments": {}}]}}).json()
    assert run["status"] == "queued"
    _drain()
    done = client.get(f"{API}/agents/runs/{run['id']}").json()
    assert done["status"] == "completed" and done["result"]["completed_steps"][0]["result"][0]["title"] == "hello"
    events = client.get(f"{API}/agents/runs/{run['id']}/events").json()
    assert events["done"] is True
    assert [e["type"] for e in events["events"]] == ["run.queued", "run.started", "step.started", "step.completed", "run.completed"]
    assert [e["sequence"] for e in events["events"]] == [1, 2, 3, 4, 5]
    assert client.get(f"{API}/agents/runs/{run['id']}/events?after_sequence=4").json()["events"][0]["type"] == "run.completed"
    stats = client.get(f"{API}/agents").json()[0]["stats"]
    assert stats["completed"] == 1 and stats["success_rate"] == 1.0
    assert client.get(f"{API}/agents/{aid}/runs").json()["total"] == 1


def test_write_step_waits_for_approval_then_resumes(client, db):
    aid = _agent(client)
    plan = {"steps": [{"tool": "notes.list", "arguments": {}}, {"tool": "tasks.create", "arguments": {"task": "Follow up"}}]}
    run = client.post(f"{API}/agents/{aid}/run", json={"input": "x", "plan": plan}).json()
    _drain()
    waiting = client.get(f"{API}/agents/runs/{run['id']}").json()
    assert waiting["status"] == "awaiting_approval" and db.query(Task).count() == 0
    approval = client.get(f"{API}/agents/approvals").json()[0]
    assert approval["tool"] == "tasks.create" and approval["arguments"] == {"task": "Follow up"} and approval["step_index"] == 1
    resolved = client.post(f"{API}/agents/approvals/{approval['id']}/resolve", json={"decision": "approved"}).json()
    assert resolved["status"] == "approved" and resolved["run_status"] == "queued"
    assert client.post(f"{API}/agents/approvals/{approval['id']}/resolve", json={"decision": "rejected"}).status_code == 409
    _drain()
    assert client.get(f"{API}/agents/runs/{run['id']}").json()["status"] == "completed"
    assert db.query(Task).filter_by(task="Follow up").count() == 1  # executed exactly once
    assert client.get(f"{API}/agents/approvals?status=executed").json()[0]["id"] == approval["id"]


def test_rejection_fails_run_and_cancel(client, db):
    aid = _agent(client)
    plan = {"steps": [{"tool": "tasks.create", "arguments": {"task": "No"}}]}
    run = client.post(f"{API}/agents/{aid}/run", json={"input": "x", "plan": plan}).json()
    _drain()
    approval = client.get(f"{API}/agents/approvals").json()[0]
    client.post(f"{API}/agents/approvals/{approval['id']}/resolve", json={"decision": "reject", "note": "nope"})
    failed = client.get(f"{API}/agents/runs/{run['id']}").json()
    assert failed["status"] == "failed" and db.query(Task).count() == 0
    queued = client.post(f"{API}/agents/{aid}/run", json={"input": "y", "plan": {"steps": []}}).json()
    assert client.post(f"{API}/agents/runs/{queued['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"{API}/agents/runs/{queued['id']}/cancel").status_code == 409


def test_invalid_plan_paused_agent_and_delete_handles_jobs(client):
    aid = _agent(client)
    assert client.post(f"{API}/agents/{aid}/run", json={"input": "x", "plan": {"steps": [{"tool": "calendar.list", "arguments": {}}]}}).status_code == 422  # not in agent's tools
    assert client.patch(f"{API}/agents/{aid}/status?status=paused").json()["status"] == "paused"
    assert client.post(f"{API}/agents/{aid}/run", json={"input": "x", "plan": {"steps": []}}).status_code == 409
    client.patch(f"{API}/agents/{aid}/status?status=active")
    job = client.post(f"{API}/automation/jobs", json={"name": "Nightly", "agent_id": aid, "trigger_type": "interval",
                                                      "trigger_config": {"interval_seconds": 3600}, "enabled": True}).json()
    queued = client.post(f"{API}/agents/{aid}/run", json={"input": "z", "plan": {"steps": []}}).json()
    deleted = client.delete(f"{API}/agents/{aid}").json()
    assert deleted == {"deleted": True, "disabled_jobs": 1, "cancelled_runs": 1}
    after = client.get(f"{API}/automation/jobs/{job['id']}").json()
    assert after["enabled"] is False and after["agent_id"] is None
    assert client.get(f"{API}/agents/runs/{queued['id']}").json()["status"] == "cancelled"


def test_overview_metrics(client):
    aid = _agent(client)
    client.post(f"{API}/agents/{aid}/run", json={"input": "x", "plan": {"steps": [{"tool": "notes.list", "arguments": {}}]}})
    _drain()
    overview = client.get(f"{API}/agents/overview").json()
    assert overview["totals"]["total"] == 1 and overview["totals"]["completed"] == 1 and len(overview["days"]) >= 7


def test_trigger_validation_and_job_crud(client):
    triggers = client.get(f"{API}/automation/triggers").json()
    assert {t["type"] for t in triggers["triggers"]} == {"manual", "interval", "cron", "event"} and triggers["events"]
    bad = [{"trigger_type": "interval", "trigger_config": {"interval_seconds": 5}}, {"trigger_type": "cron", "trigger_config": {"expression": "nope"}},
           {"trigger_type": "event", "trigger_config": {"event": "nope"}}, {"trigger_type": "event", "trigger_config": {"event": "task.created", "filters": {"zzz": 1}}}]
    for extra in bad:
        assert client.post(f"{API}/automation/jobs", json={"name": "j", **extra}).status_code == 422, extra
    job = client.post(f"{API}/automation/jobs", json={"name": "Daily", "trigger_type": "cron", "trigger_config": {"expression": "0 9 * * *", "timezone": "Asia/Kolkata"}}).json()
    assert job["enabled"] is False
    assert client.patch(f"{API}/automation/jobs/{job['id']}/enabled?enabled=true").json()["enabled"] is True
    assert client.put(f"{API}/automation/jobs/{job['id']}", json={"name": "Renamed", "trigger_type": "manual"}).json()["name"] == "Renamed"
    run = client.post(f"{API}/automation/jobs/{job['id']}/run")
    assert run.status_code == 202
    history = client.get(f"{API}/automation/jobs/{job['id']}/runs").json()
    assert history["total"] == 1 and history["items"][0]["trigger"] == "manual"
    summary = client.get(f"{API}/automation/summary").json()
    assert summary["jobs_total"] == 1 and summary["runs_total"] == 1
    assert client.delete(f"{API}/automation/jobs/{job['id']}").status_code == 204


def test_scheduler_interval_and_cron(client, db):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 26, 10, 30, 20, tzinfo=timezone.utc)
    interval = AutomationJob(name="i", trigger_type="interval", trigger_config=json.dumps({"interval_seconds": 60}), enabled=True,
                             last_run_at=now - timedelta(minutes=5))
    recent = AutomationJob(name="r", trigger_type="interval", trigger_config=json.dumps({"interval_seconds": 3600}), enabled=True,
                           last_run_at=now - timedelta(minutes=5))
    cron = AutomationJob(name="c", trigger_type="cron", trigger_config=json.dumps({"expression": "30 10 * * *"}), enabled=True)
    disabled = AutomationJob(name="d", trigger_type="interval", trigger_config=json.dumps({"interval_seconds": 60}), enabled=False)
    db.add_all([interval, recent, cron, disabled]); db.commit()
    assert auto.run_due_jobs(db, now) == 2  # the due interval job and the matching cron job
    assert auto.run_due_jobs(db, now) == 0  # nothing runs twice within the same interval / cron minute
    runs = db.query(AgentRun).all()
    assert {r.trigger for r in runs} == {"schedule"} and len(runs) == 2
    assert auto.run_due_jobs(db, now + timedelta(seconds=61)) == 1  # interval job is due again; cron minute has passed


def test_event_triggers_respect_filters(client, db):
    match = AutomationJob(name="m", trigger_type="event", enabled=True,
                          trigger_config=json.dumps({"event": "task.status_changed", "filters": {"to_status": "done"}}))
    other = AutomationJob(name="o", trigger_type="event", enabled=True, trigger_config=json.dumps({"event": "note.created"}))
    db.add_all([match, other]); db.commit()
    task = client.post(f"{API}/tasks", json={"task": "T"}).json()
    client.patch(f"{API}/tasks/{task['id']}/status", json={"status": "in_progress"})
    assert db.query(AgentRun).count() == 0  # filter requires to_status=done
    client.patch(f"{API}/tasks/{task['id']}/status", json={"status": "done"})
    runs = db.query(AgentRun).all()
    assert len(runs) == 1 and runs[0].trigger == "event" and runs[0].job_id == match.id and "task.status_changed" in runs[0].goal


def test_automation_skip_if_running_prevents_overlapping_runs(client, db):
    job = client.post(f"{API}/automation/jobs", json={
        "name": "No overlap", "trigger_type": "interval", "trigger_config": {"interval_seconds": 60},
        "enabled": True, "skip_if_running": True,
    })
    assert job.status_code == 201, job.text
    first = client.post(f"{API}/automation/jobs/{job.json()['id']}/run").json()
    # Only in-flight work blocks a new run (a merely queued run does not), so mark the first as running.
    run = db.get(AgentRun, first["run_id"])
    run.status = "running"
    db.commit()
    second = client.post(f"{API}/automation/jobs/{job.json()['id']}/run").json()
    assert first["status"] == "queued" and first["run_id"]
    assert second == {"job_id": job.json()["id"], "run_id": None, "status": "skipped"}
    assert client.get(f"{API}/automation/jobs/{job.json()['id']}/runs").json()["total"] == 1


def test_whitespace_only_resource_names_are_rejected(client):
    assert client.post(f"{API}/agents", json={"name": "   "}).status_code == 422
    assert client.post(f"{API}/automation/jobs", json={"name": "   "}).status_code == 422
    assert client.post(f"{API}/mcp/servers", json={"name": "   ", "transport": "http", "url": "https://example.com/mcp"}).status_code == 422
