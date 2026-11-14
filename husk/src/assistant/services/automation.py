"""Automation jobs: trigger validation, event bus, run enqueueing and the scheduler loop."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.core.cron import CronError, cron_matches, validate_cron
from assistant.core.timeutil import ensure_utc, utcnow
from assistant.db.models import Agent, AgentRun, AutomationJob
from assistant.db.session import SessionLocal
from assistant.services.agent_runtime.events import record_event

log = logging.getLogger("assistant.automation")

TRIGGER_TYPES = ("manual", "interval", "cron", "event")

# name -> description and payload fields (usable in a job's `filters`)
EVENT_CATALOG: dict[str, dict] = {
    "conversation.created": {"description": "A conversation was created", "fields": ["id", "title"]},
    "task.created": {"description": "A task was created", "fields": ["id", "task", "status", "due_at", "position"]},
    "task.status_changed": {"description": "A task moved to another status",
                            "fields": ["id", "task", "status", "due_at", "position", "from_status", "to_status"]},
    "note.created": {"description": "A note was created", "fields": ["id", "title", "color", "pinned"]},
    "note.updated": {"description": "A note was edited", "fields": ["id", "title", "color", "pinned"]},
    "calendar.event_created": {"description": "A calendar event was created", "fields": ["id", "title", "start_at", "end_at", "location"]},
    "mail.message_received": {"description": "A new inbox email arrived during sync",
                              "fields": ["id", "account_id", "subject", "sender_email", "folder"]},
    "agent.run_failed": {"description": "An agent run failed", "fields": ["run_id", "agent_id", "error"]},
    "approval.requested": {"description": "An agent run is waiting for approval", "fields": ["approval_id", "run_id", "tool"]},
}


class AgentPausedError(RuntimeError):
    pass


def trigger_catalog() -> dict:
    return {
        "triggers": [
            {"type": "manual", "description": "Only runs when you start it", "config_fields": []},
            {"type": "interval", "description": "Runs every N seconds (minimum 60)",
             "config_fields": [{"name": "interval_seconds", "type": "integer", "required": True, "minimum": 60}]},
            {"type": "cron", "description": "Runs on a 5-field cron schedule (minute hour day month weekday)",
             "config_fields": [{"name": "expression", "type": "string", "required": True, "example": "0 9 * * 1-5"},
                               {"name": "timezone", "type": "string", "required": False, "example": "Asia/Kolkata", "default": "UTC"}]},
            {"type": "event", "description": "Runs when an application event occurs",
             "config_fields": [{"name": "event", "type": "string", "required": True, "enum": sorted(EVENT_CATALOG)},
                               {"name": "filters", "type": "object", "required": False,
                                "description": "Field/value pairs that must all match the event payload"}]},
        ],
        "events": [{"name": name, **info} for name, info in sorted(EVENT_CATALOG.items())],
    }


def validate_trigger(trigger_type: str, config: dict) -> dict:
    """Return a normalised config or raise ``ValueError``."""
    if trigger_type not in TRIGGER_TYPES:
        raise ValueError(f"trigger_type must be one of {', '.join(TRIGGER_TYPES)}")
    if not isinstance(config, dict):
        raise ValueError("trigger_config must be an object")
    if trigger_type == "interval":
        seconds = config.get("interval_seconds")
        if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 60:
            raise ValueError("interval_seconds must be an integer >= 60")
    elif trigger_type == "cron":
        try:
            validate_cron(str(config.get("expression", "")))
        except CronError as exc:
            raise ValueError(f"Invalid cron expression: {exc}") from exc
        tz = config.get("timezone", "UTC")
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError(f"Unknown timezone: {tz}") from exc
    elif trigger_type == "event":
        event = config.get("event")
        if event not in EVENT_CATALOG:
            raise ValueError(f"event must be one of: {', '.join(sorted(EVENT_CATALOG))}")
        filters = config.get("filters", {})
        if not isinstance(filters, dict):
            raise ValueError("filters must be an object")
        unknown = set(filters) - set(EVENT_CATALOG[event]["fields"])
        if unknown:
            raise ValueError(f"Unknown filter fields for {event}: {', '.join(sorted(unknown))}")
    return config


def job_goal(job: AutomationJob) -> str:
    return (job.input or job.description or job.name)[:10000]


def enqueue_job_run(db: Session, job: AutomationJob, *, trigger: str, extra_input: str = "",
                    now: datetime | None = None) -> AgentRun | None:
    """Queue a run for ``job``.  Adds to the session without committing.

    Returns ``None`` (skipping silently) for unattended triggers when the linked agent is paused;
    raises ``AgentPausedError`` for a manual run so the person gets told.
    """
    if job.skip_if_running:
        # Only treat in-flight work as blocking. "queued" alone must not prevent the next
        # interval/cron tick (otherwise a stuck queue permanently silences the schedule).
        active_run = db.scalar(select(AgentRun.id).where(
            AgentRun.job_id == job.id, AgentRun.status.in_(("running", "awaiting_approval"))
        ).limit(1))
        if active_run:
            return None
    if job.agent_id:
        agent = db.get(Agent, job.agent_id)
        if agent is not None and agent.status != "active":
            if trigger == "manual":
                raise AgentPausedError("The agent linked to this job is paused")
            return None
    goal = job_goal(job) + (("\n\n" + extra_input) if extra_input else "")
    run = AgentRun(goal=goal[:10000], agent_id=job.agent_id, job_id=job.id, trigger=trigger, status="queued")
    db.add(run)
    db.flush()
    record_event(db, run.id, "run.queued", "Automation job queued", {"job_id": job.id, "trigger": trigger})
    job.last_run_at = now or utcnow()
    job.run_count = int(job.run_count or 0) + 1
    return run


def fire_event(db: Session, name: str, payload: dict) -> int:
    """Queue runs for enabled event jobs whose filters match.  Call before ``db.commit()``."""
    queued = 0
    jobs = db.scalars(select(AutomationJob).where(AutomationJob.enabled.is_(True), AutomationJob.trigger_type == "event"))
    for job in jobs.all():
        try:
            config = json.loads(job.trigger_config or "{}")
        except json.JSONDecodeError:
            continue
        if config.get("event") != name:
            continue
        filters = config.get("filters") or {}
        if any(str(payload.get(key)) != str(value) for key, value in filters.items()):
            continue
        extra = f"Trigger event: {name}\nPayload: {json.dumps(payload, default=str)[:2000]}"
        if enqueue_job_run(db, job, trigger="event", extra_input=extra):
            queued += 1
    return queued


def _cron_was_due_since(expr: str, tz_name: str, last: datetime | None, now: datetime) -> bool:
    """True if the cron expression matched at least once in (last, now] (UTC-aware).

    Used for catch-up after downtime: if the process was offline when the minute hit,
    we still enqueue once on the next scheduler tick instead of silently skipping.
    Looks back at most 7 days to avoid long catch-up storms.
    """
    try:
        tz = ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        tz = ZoneInfo("UTC")
    now = ensure_utc(now) or utcnow()
    # Cap look-back so a long outage does not queue dozens of historical runs.
    window_start = now - timedelta(days=7)
    if last is not None:
        last = ensure_utc(last)
        if last > window_start:
            window_start = last
    # Walk minute-by-minute from the first minute after window_start up to current minute.
    cursor = (window_start + timedelta(minutes=1)).replace(second=0, microsecond=0)
    end_minute = now.replace(second=0, microsecond=0)
    # Hard limit iterations (7 days * 1440 ≈ 10k); stop early on first match.
    for _ in range(10_080):
        if cursor > end_minute:
            break
        local = cursor.astimezone(tz)
        if cron_matches(expr, local):
            return True
        cursor += timedelta(minutes=1)
    return False


def run_due_jobs(db: Session, now: datetime | None = None) -> int:
    """Enqueue interval and cron jobs that are due (including one catch-up after downtime).

    Commits.  Returns how many runs were queued.
    """
    now = ensure_utc(now) or utcnow()
    queued = 0
    jobs = db.scalars(select(AutomationJob).where(
        AutomationJob.enabled.is_(True), AutomationJob.trigger_type.in_(("interval", "cron")))).all()
    for job in jobs:
        try:
            config = json.loads(job.trigger_config or "{}")
            last = ensure_utc(job.last_run_at)
            if job.trigger_type == "interval":
                interval = int(config.get("interval_seconds", 0))
                if interval < 60:
                    continue
                baseline = last or ensure_utc(job.updated_at) or ensure_utc(job.created_at)
                if (now - baseline).total_seconds() < interval:
                    continue
            else:
                expr = config.get("expression", "")
                tz_name = config.get("timezone", "UTC")
                local_now = now.astimezone(ZoneInfo(tz_name))
                minute_start = now.replace(second=0, microsecond=0)
                # Fire if this exact minute matches, or if we missed a previous match while offline.
                current_match = cron_matches(expr, local_now)
                if current_match:
                    if last is not None and last >= minute_start:
                        continue  # already ran during this minute
                else:
                    if not _cron_was_due_since(expr, tz_name, last, now):
                        continue
            if enqueue_job_run(db, job, trigger="schedule", now=now):
                queued += 1
        except (ValueError, TypeError, CronError, ZoneInfoNotFoundError, json.JSONDecodeError):
            log.warning("Skipping job %s: malformed trigger config", job.id, extra={"category": "automation"})
    db.commit()
    return queued


async def scheduler_loop(stop_event: asyncio.Event, poll_seconds: int = 15) -> None:
    from assistant.services.maintenance import run_maintenance

    last_maintenance = datetime.min.replace(tzinfo=timezone.utc)
    while not stop_event.is_set():
        def tick() -> None:
            nonlocal last_maintenance
            with SessionLocal() as db:
                try:
                    run_due_jobs(db)
                    if utcnow() - last_maintenance > timedelta(hours=1):
                        run_maintenance(db)
                        last_maintenance = utcnow()
                except Exception:  # noqa: BLE001
                    db.rollback()
                    log.exception("Scheduler tick failed", extra={"category": "automation"})
        await asyncio.to_thread(tick)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            pass
