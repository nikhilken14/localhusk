from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import PageParams, Pagination, get_db
from assistant.api.v1.agents import run_out
from assistant.core.errors import APIError
from assistant.core.timeutil import ensure_utc, utcnow
from assistant.db.models import Agent, AgentRun, AutomationJob
from assistant.schemas.automation import JobIn
from assistant.services import automation as svc

router = APIRouter(prefix="/automation", tags=["automation"])


def job_out(job: AutomationJob, db: Session) -> dict:
    config = json.loads(job.trigger_config or "{}")
    agent = db.get(Agent, job.agent_id) if job.agent_id else None
    latest = db.scalars(select(AgentRun).where(AgentRun.job_id == job.id).order_by(AgentRun.created_at.desc()).limit(1)).first()
    next_run = None
    if job.enabled and job.trigger_type == "interval" and isinstance(config.get("interval_seconds"), int):
        baseline = ensure_utc(job.last_run_at or job.updated_at)
        next_run = baseline + timedelta(seconds=config["interval_seconds"])
    # Cron next-fire is computed by the scheduler; surface last known schedule only for interval here.
    return {"id": job.id, "name": job.name, "description": job.description, "trigger_type": job.trigger_type,
            "trigger_config": config, "agent_id": job.agent_id, "agent_name": agent.name if agent else None,
            "agent_status": agent.status if agent else None, "input": job.input, "input_template": job.input,
            "enabled": job.enabled,
            "skip_if_running": job.skip_if_running, "run_count": job.run_count, "last_run_at": job.last_run_at,
            "last_run_id": latest.id if latest else None, "last_run_status": latest.status if latest else None,
            "last_status": latest.status if latest else None, "next_run_at": next_run,
            "created_at": job.created_at, "updated_at": job.updated_at}


def _get(db: Session, job_id: str) -> AutomationJob:
    job = db.get(AutomationJob, job_id)
    if job is None:
        raise APIError(404, "Automation job not found")
    return job


def _apply(db: Session, job: AutomationJob, payload: JobIn) -> None:
    try:
        config = svc.validate_trigger(payload.trigger_type, payload.trigger_config)
    except ValueError as exc:
        raise APIError(422, str(exc)) from exc
    if payload.agent_id and db.get(Agent, payload.agent_id) is None:
        raise APIError(404, "Agent not found")
    job.name = payload.name.strip()
    if payload.description is not None:
        job.description = payload.description
    job.input = payload.input
    job.trigger_type, job.trigger_config = payload.trigger_type, json.dumps(config)
    job.agent_id, job.enabled, job.skip_if_running = payload.agent_id, payload.enabled, payload.skip_if_running


# static routes before /jobs/{id}
@router.get("/summary", summary="Workflow and success-rate metrics")
def summary(db: Session = Depends(get_db)):
    jobs = db.scalars(select(AutomationJob)).all()
    by_trigger: dict[str, int] = {}
    for job in jobs:
        by_trigger[job.trigger_type] = by_trigger.get(job.trigger_type, 0) + 1
    counts = dict(db.execute(select(AgentRun.status, func.count(AgentRun.id)).where(AgentRun.job_id.is_not(None)).group_by(AgentRun.status)).all())
    day_ago = utcnow() - timedelta(hours=24)
    week_ago = utcnow() - timedelta(days=7)
    runs_24h = db.scalar(select(func.count(AgentRun.id)).where(AgentRun.job_id.is_not(None), AgentRun.created_at >= day_ago)) or 0
    runs_7d = db.scalar(select(func.count(AgentRun.id)).where(AgentRun.job_id.is_not(None), AgentRun.created_at >= week_ago)) or 0
    finished = counts.get("completed", 0) + counts.get("failed", 0)
    scheduled = [job_out(j, db) for j in jobs if j.enabled]
    scheduled = [j for j in scheduled if j.get("next_run_at") is not None]
    scheduled.sort(key=lambda j: j["next_run_at"])
    next_run = {"at": scheduled[0]["next_run_at"], "name": scheduled[0]["name"]} if scheduled else None
    return {"jobs_total": len(jobs), "jobs_enabled": sum(j.enabled for j in jobs), "jobs_by_trigger": by_trigger,
            "runs_total": sum(counts.values()), "runs_last_24h": runs_24h, "runs_last_7d": runs_7d, "runs_by_status": counts,
            "success_rate": round(counts.get("completed", 0) / finished * 100, 2) if finished else None,
            "last_run_at": max((j.last_run_at for j in jobs if j.last_run_at), default=None),
            "next_run": next_run}


@router.get("/triggers", summary="Supported trigger types and event triggers with their fields")
def triggers():
    return svc.trigger_catalog()


@router.get("/jobs")
def list_jobs(enabled: bool | None = None, db: Session = Depends(get_db)):
    stmt = select(AutomationJob).order_by(AutomationJob.created_at.desc())
    if enabled is not None:
        stmt = stmt.where(AutomationJob.enabled.is_(enabled))
    return [job_out(j, db) for j in db.scalars(stmt)]


@router.post("/jobs", status_code=201)
def create_job(payload: JobIn, db: Session = Depends(get_db)):
    job = AutomationJob()
    _apply(db, job, payload)
    db.add(job)
    db.commit()
    return job_out(job, db)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db)):
    return job_out(_get(db, job_id), db)


@router.put("/jobs/{job_id}")
def update_job(job_id: str, payload: JobIn, db: Session = Depends(get_db)):
    job = _get(db, job_id)
    _apply(db, job, payload)
    db.commit()
    return job_out(job, db)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, job_id))  # run history stays (job_id -> NULL)
    db.commit()


@router.patch("/jobs/{job_id}/enabled", summary="Enable or disable: ?enabled=true|false")
def set_enabled(job_id: str, enabled: bool, db: Session = Depends(get_db)):
    job = _get(db, job_id)
    job.enabled = enabled  # updated_at moves, which restarts an interval job's countdown
    db.commit()
    return job_out(job, db)


@router.post("/jobs/{job_id}/run", status_code=202, summary="Execute a job now (works even when disabled)")
def run_now(job_id: str, db: Session = Depends(get_db)):
    job = _get(db, job_id)
    try:
        run = svc.enqueue_job_run(db, job, trigger="manual")
    except svc.AgentPausedError as exc:
        raise APIError(409, str(exc), "agent_paused") from exc
    db.commit()
    return {"job_id": job.id, "run_id": run.id if run else None, "status": run.status if run else "skipped"}


@router.get("/jobs/{job_id}/runs", summary="Execution history")
def job_runs(job_id: str, status: str | None = None, page: Pagination = PageParams, db: Session = Depends(get_db)):
    _get(db, job_id)
    conditions = [AgentRun.job_id == job_id] + ([AgentRun.status == status] if status else [])
    total = db.scalar(select(func.count(AgentRun.id)).where(*conditions)) or 0
    rows = db.scalars(select(AgentRun).where(*conditions).order_by(AgentRun.created_at.desc()).limit(page.limit).offset(page.offset))
    return {"items": [run_out(r) for r in rows], "total": total, "limit": page.limit, "offset": page.offset}
