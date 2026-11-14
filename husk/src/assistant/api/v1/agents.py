from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import PageParams, Pagination, get_db
from assistant.core.errors import APIError
from assistant.core.timeutil import ensure_utc, utcnow
from assistant.db.models import Agent, AgentApproval, AgentRun, AgentRunEvent, AutomationJob, ProviderConfig
from assistant.schemas.agents import AgentIn, ResolveIn, RunIn
from assistant.schemas.common import Page
from assistant.services import llm
from assistant.services import attachments as att_service
from assistant.services.agent_runtime import tools
from assistant.services.agent_runtime.events import event_out, record_event
from assistant.services.agent_runtime.planner import validate_plan

router = APIRouter(prefix="/agents", tags=["agents"])
TERMINAL = ("completed", "failed", "cancelled")
STAT_KEYS = ("completed", "failed", "cancelled", "running", "queued", "awaiting_approval", "deferred")


# ------------------------------------------------------------------ serialisers
def _loads(raw: str | None, default):
    try:
        return json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default


def run_out(run: AgentRun) -> dict:
    duration = None
    if run.started_at and run.finished_at:
        duration = int((run.finished_at - run.started_at).total_seconds() * 1000)
    return {"id": run.id, "agent_id": run.agent_id, "job_id": run.job_id, "trigger": run.trigger, "input": run.goal,
            "status": run.status, "plan": _loads(run.plan_json, None), "result": _loads(run.result, None), "error": run.error,
            "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
            "retry_count": getattr(run, "retry_count", 0) or 0,
            "next_retry_at": getattr(run, "next_retry_at", None),
            "started_at": run.started_at,
            "finished_at": run.finished_at, "duration_ms": duration, "created_at": run.created_at, "updated_at": run.updated_at}


def approval_out(a: AgentApproval, run: AgentRun | None = None, agent_name: str | None = None) -> dict:
    return {"id": a.id, "run_id": a.run_id, "step_index": a.step_index, "tool": a.action,
            "arguments": _loads(a.details, {}).get("arguments", {}), "status": a.status, "note": a.resolution_note,
            "run_input": run.goal if run else None, "agent_id": run.agent_id if run else None, "agent_name": agent_name,
            "created_at": a.created_at, "decided_at": a.decided_at}


def _stats(db: Session, agent_ids: list[str]) -> dict[str, dict]:
    stats = {aid: {"total_runs": 0, **{k: 0 for k in STAT_KEYS}, "success_rate": None, "last_run_at": None,
                   "runs_7d": 0, "input_tokens": 0, "output_tokens": 0,
                   "last_run_id": None, "last_run_status": None} for aid in agent_ids}
    if not agent_ids:
        return stats
    for aid, status, count, last, tin, tout in db.execute(
            select(AgentRun.agent_id, AgentRun.status, func.count(AgentRun.id), func.max(AgentRun.created_at),
                   func.sum(AgentRun.input_tokens), func.sum(AgentRun.output_tokens))
            .where(AgentRun.agent_id.in_(agent_ids)).group_by(AgentRun.agent_id, AgentRun.status)):
        s = stats[aid]
        s["total_runs"] += count
        if status in STAT_KEYS:
            s[status] = count
        s["input_tokens"] += int(tin or 0)
        s["output_tokens"] += int(tout or 0)
        if last and (s["last_run_at"] is None or last > s["last_run_at"]):
            s["last_run_at"] = last
    week_ago = utcnow() - timedelta(days=7)
    for aid, count in db.execute(
            select(AgentRun.agent_id, func.count(AgentRun.id))
            .where(AgentRun.agent_id.in_(agent_ids), AgentRun.created_at >= week_ago)
            .group_by(AgentRun.agent_id)):
        stats[aid]["runs_7d"] = int(count)
    # Latest run id/status per agent (one query ordered by created_at desc)
    latest_rows = db.execute(
        select(AgentRun.agent_id, AgentRun.id, AgentRun.status, AgentRun.created_at)
        .where(AgentRun.agent_id.in_(agent_ids))
        .order_by(AgentRun.created_at.desc())
    ).all()
    seen: set[str] = set()
    for aid, rid, status, _created in latest_rows:
        if aid in seen:
            continue
        seen.add(aid)
        stats[aid]["last_run_id"] = rid
        stats[aid]["last_run_status"] = status
    for s in stats.values():
        finished = s["completed"] + s["failed"]
        s["success_rate"] = round(s["completed"] / finished, 4) if finished else None
    return stats


def agent_out(agent: Agent, stats: dict | None = None, automation_names: list[str] | None = None) -> dict:
    s = stats or {}
    tools = _loads(agent.tools_json, [])
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "provider_id": agent.provider_id,
        "tools": tools,
        "tool_count": len(tools) if isinstance(tools, list) else 0,
        "status": agent.status,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "stats": s,
        "last_run_id": s.get("last_run_id"),
        "last_run_status": s.get("last_run_status"),
        "automation_names": automation_names or [],
    }


def _get_agent(db: Session, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise APIError(404, "Agent not found")
    return agent


def _validate(db: Session, payload: AgentIn) -> None:
    if payload.provider_id and db.get(ProviderConfig, payload.provider_id) is None:
        raise APIError(404, "Model connection not found")
    try:
        tools.validate_tool_ids(db, payload.tools)
    except ValueError as exc:
        raise APIError(422, str(exc)) from exc


def _get_run(db: Session, run_id: str) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise APIError(404, "Agent run not found")
    return run


def cancel_run(db: Session, run: AgentRun, reason: str) -> None:
    """Cancel a run that hasn't finished.  A step already in flight completes; later steps are skipped."""
    for approval in db.scalars(select(AgentApproval).where(AgentApproval.run_id == run.id, AgentApproval.status == "pending")):
        approval.status, approval.decided_at, approval.resolution_note = "rejected", utcnow(), "Run cancelled"
    run.status, run.finished_at = "cancelled", utcnow()
    record_event(db, run.id, "run.cancelled", reason)


# ------------------------------------------------------------------ static routes first
@router.get("/catalog", summary="Tools (built-in + MCP) and models an agent can use")
def agent_catalog(db: Session = Depends(get_db)):
    models = [{"id": p.id, "name": p.name, "kind": p.kind, "model": p.model, "is_default": p.is_default}
              for p in db.scalars(select(ProviderConfig).order_by(ProviderConfig.created_at))]
    return {"tools": tools.catalog(db), "models": models}


@router.get("/overview", summary="Daily run metrics")
def agent_overview(since: datetime | None = Query(None, description="ISO start; default 7 days ago"),
                   tz_offset_minutes: int = Query(0, ge=-840, le=840, description="Bucket days in the client's zone"),
                   db: Session = Depends(get_db)):
    now = utcnow()
    start = ensure_utc(since) or now - timedelta(days=7)
    if now - start > timedelta(days=366):
        raise APIError(422, "since may be at most 366 days ago")
    offset = timedelta(minutes=tz_offset_minutes)
    days: dict[str, dict] = {}
    cursor = (start + offset).date()
    while cursor <= (now + offset).date():
        days[cursor.isoformat()] = {"date": cursor.isoformat(), "total": 0, **{k: 0 for k in STAT_KEYS},
                                    "input_tokens": 0, "output_tokens": 0}
        cursor += timedelta(days=1)
    totals = {"total": 0, **{k: 0 for k in STAT_KEYS}, "input_tokens": 0, "output_tokens": 0}
    durations: list[float] = []
    for run in db.scalars(select(AgentRun).where(AgentRun.created_at >= start)):
        bucket = days.setdefault((run.created_at + offset).date().isoformat(), {"date": (run.created_at + offset).date().isoformat(),
                                 "total": 0, **{k: 0 for k in STAT_KEYS}, "input_tokens": 0, "output_tokens": 0})
        for target in (bucket, totals):
            target["total"] += 1
            if run.status in STAT_KEYS:
                target[run.status] += 1
            target["input_tokens"] += run.input_tokens
            target["output_tokens"] += run.output_tokens
        if run.started_at and run.finished_at:
            durations.append((run.finished_at - run.started_at).total_seconds() * 1000)
    finished = totals["completed"] + totals["failed"]
    pending = db.scalar(select(func.count(AgentApproval.id)).where(AgentApproval.status == "pending")) or 0
    return {"since": start, "days": [days[k] for k in sorted(days)],
            "totals": {**totals, "success_rate": round(totals["completed"] / finished, 4) if finished else None,
                       "avg_duration_ms": int(sum(durations) / len(durations)) if durations else None},
            "pending_approvals": pending}


@router.get("/approvals", summary="Approvals (pending by default)")
def list_approvals(status: Literal["pending", "approved", "rejected", "executed", "all"] = "pending",
                   run_id: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(AgentApproval, AgentRun, Agent.name).join(AgentRun, AgentApproval.run_id == AgentRun.id) \
        .join(Agent, AgentRun.agent_id == Agent.id, isouter=True).order_by(AgentApproval.created_at.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(AgentApproval.status == status)
    if run_id:
        stmt = stmt.where(AgentApproval.run_id == run_id)
    return [approval_out(a, r, name) for a, r, name in db.execute(stmt)]


@router.post("/approvals/{approval_id}/resolve", summary="Approve or reject a pending operation")
def resolve_approval(approval_id: str, payload: ResolveIn, db: Session = Depends(get_db)):
    approval = db.get(AgentApproval, approval_id)
    if approval is None:
        raise APIError(404, "Approval not found")
    if approval.status != "pending":
        raise APIError(409, "This approval has already been resolved", "already_resolved")
    run = db.get(AgentRun, approval.run_id)
    decision = payload.normalized
    approval.status, approval.decided_at, approval.resolution_note = decision, utcnow(), payload.note
    record_event(db, approval.run_id, f"approval.{decision}", f"Approval {decision}", {"approval_id": approval.id, "tool": approval.action})
    if run and run.status == "awaiting_approval":
        if decision == "approved":
            run.status = "queued"  # the worker resumes at this step
        else:
            run.status, run.error, run.finished_at = "failed", "Required action was rejected", utcnow()
            record_event(db, run.id, "run.failed", run.error)
    db.commit()
    return {**approval_out(approval, run), "run_status": run.status if run else None}


@router.get("/runs/{run_id}", summary="Run details and status")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    pending = db.scalars(select(AgentApproval).where(AgentApproval.run_id == run_id, AgentApproval.status == "pending")).all()
    return {**run_out(run), "pending_approvals": [approval_out(a, run) for a in pending]}


@router.get("/runs/{run_id}/events", summary="Poll trace events; pass the last `next_sequence` as after_sequence")
def run_events(run_id: str, after_sequence: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=500), db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    events = db.scalars(select(AgentRunEvent).where(AgentRunEvent.run_id == run_id, AgentRunEvent.sequence > after_sequence)
                        .order_by(AgentRunEvent.sequence).limit(limit)).all()
    return {"run_id": run_id, "run_status": run.status, "done": run.status in TERMINAL, "events": [event_out(e) for e in events],
            "next_sequence": events[-1].sequence if events else after_sequence}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    if run.status in TERMINAL:
        raise APIError(409, "This run has already finished", "already_finished")
    cancel_run(db, run, "Agent run cancelled by user")
    db.commit()
    return {"run_id": run.id, "status": run.status}


# ------------------------------------------------------------------ agents CRUD
@router.get("/runs", summary="Global run ledger (all agents and automations)")
def list_all_runs(limit: int = Query(100, ge=1, le=500), status: str | None = None,
                  agent_id: str | None = None, job_id: str | None = None, db: Session = Depends(get_db)):
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    if agent_id:
        stmt = stmt.where(AgentRun.agent_id == agent_id)
    if job_id:
        stmt = stmt.where(AgentRun.job_id == job_id)
    rows = db.scalars(stmt).all()
    return {"items": [run_out(r) for r in rows], "total": len(rows)}


@router.get("", summary="Agents with run statistics")
def list_agents(db: Session = Depends(get_db)):
    agents = db.scalars(select(Agent).order_by(Agent.created_at)).all()
    stats = _stats(db, [a.id for a in agents])
    # automation names used by each agent
    names_by_agent: dict[str, list[str]] = {a.id: [] for a in agents}
    for job in db.scalars(select(AutomationJob).where(AutomationJob.agent_id.is_not(None))):
        if job.agent_id in names_by_agent:
            names_by_agent[job.agent_id].append(job.name)
    return [agent_out(a, stats[a.id], names_by_agent.get(a.id, [])) for a in agents]


@router.post("", status_code=201)
def create_agent(payload: AgentIn, db: Session = Depends(get_db)):
    _validate(db, payload)
    status = payload.status if payload.status is not None else "active"
    agent = Agent(name=payload.name.strip(), description=payload.description, system_prompt=payload.system_prompt,
                  provider_id=payload.provider_id, tools_json=json.dumps(payload.tools), status=status)
    db.add(agent)
    db.commit()
    return agent_out(agent, _stats(db, [agent.id])[agent.id])


@router.get("/{agent_id}")
def get_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    names = [j.name for j in db.scalars(select(AutomationJob).where(AutomationJob.agent_id == agent_id))]
    return agent_out(agent, _stats(db, [agent.id])[agent.id], names)


@router.put("/{agent_id}")
def update_agent(agent_id: str, payload: AgentIn, db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    _validate(db, payload)
    agent.name, agent.description, agent.system_prompt = payload.name.strip(), payload.description, payload.system_prompt
    agent.provider_id, agent.tools_json = payload.provider_id, json.dumps(payload.tools)
    # Only change status when explicitly provided — avoids re-activating paused agents on edit.
    if payload.status is not None:
        agent.status = payload.status
    db.commit()
    names = [j.name for j in db.scalars(select(AutomationJob).where(AutomationJob.agent_id == agent_id))]
    return agent_out(agent, _stats(db, [agent.id])[agent.id], names)


@router.delete("/{agent_id}", summary="Delete an agent; linked jobs are disabled and unfinished runs cancelled")
def delete_agent(agent_id: str, db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    jobs = db.scalars(select(AutomationJob).where(AutomationJob.agent_id == agent_id)).all()
    for job in jobs:  # a job must never silently start running as a different (agent-less) workflow
        job.enabled, job.agent_id = False, None
    cancelled = 0
    for run in db.scalars(select(AgentRun).where(AgentRun.agent_id == agent_id, AgentRun.status.in_(("queued", "awaiting_approval", "deferred")))):
        cancel_run(db, run, "Agent was deleted")
        cancelled += 1
    db.delete(agent)  # remaining runs keep their history (agent_id -> NULL)
    db.commit()
    return {"deleted": True, "disabled_jobs": len(jobs), "cancelled_runs": cancelled}


@router.patch("/{agent_id}/status", summary="Activate or pause: ?status=active|paused")
def set_agent_status(agent_id: str, status: Literal["active", "paused"], db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    agent.status = status
    db.commit()
    return agent_out(agent)


@router.post("/{agent_id}/attachments", status_code=201, summary="Upload a document for agent runs")
async def upload_agent_attachment(
    agent_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Accept pdf, docx, xlsx, zip, txt, md, csv, json. Extracted text is available to the next run."""
    agent = _get_agent(db, agent_id)
    data = await file.read()
    row = att_service.save_upload(
        db,
        agent=agent,
        filename=file.filename or "file",
        data=data,
        content_type=file.content_type,
    )
    db.commit()
    db.refresh(row)
    return att_service.attachment_public(row)


@router.get("/{agent_id}/attachments", summary="List documents uploaded for an agent")
def list_agent_attachments(agent_id: str, db: Session = Depends(get_db)):
    _get_agent(db, agent_id)
    return [att_service.attachment_public(r) for r in att_service.list_for_agent(db, agent_id)]


@router.delete("/{agent_id}/attachments/{attachment_id}", status_code=204, summary="Delete an agent attachment")
def delete_agent_attachment(agent_id: str, attachment_id: str, db: Session = Depends(get_db)):
    _get_agent(db, agent_id)
    row = att_service.get_attachment(db, attachment_id)
    if row.agent_id != agent_id:
        raise APIError(404, "Attachment not found")
    att_service.delete_attachment(db, row)
    db.commit()
    return None


@router.post("/{agent_id}/run", status_code=202, summary="Start an execution")
def start_run(agent_id: str, payload: RunIn, db: Session = Depends(get_db)):
    agent = _get_agent(db, agent_id)
    if agent.status != "active":
        raise APIError(409, "This agent is paused", "agent_paused")
    attachments = att_service.resolve_for_agent(db, agent.id, payload.attachment_ids or None)
    user_text = (payload.input or "").strip()
    if not user_text and not attachments and payload.plan is None:
        raise APIError(400, "Provide input text, attachments, or a pre-built plan")
    goal = att_service.build_user_content_with_attachments(user_text, attachments) if attachments else user_text
    if not goal and payload.plan is not None:
        goal = user_text or "(pre-built plan)"
    plan_json = None
    if payload.plan is not None:
        try:
            plan_json = json.dumps(validate_plan(payload.plan, tools.allowed_tools(db, json.loads(agent.tools_json))))
        except ValueError as exc:
            raise APIError(422, f"Invalid plan: {exc}") from exc
    else:
        # Do not fail hard if the model is offline — queue the run and let the worker defer it.
        try:
            llm.resolve_provider(db, agent.provider_id)
        except Exception:  # noqa: BLE001
            pass
    run = AgentRun(agent_id=agent.id, goal=goal[:10000], plan_json=plan_json, trigger="manual", status="queued")
    db.add(run)
    db.flush()
    if attachments:
        att_service.bind_to_run(db, attachments, run.id)
        names = ", ".join(a.filename for a in attachments)
        record_event(db, run.id, "run.queued", f"Agent run queued with attachments: {names}",
                     {"agent_id": agent.id, "attachment_ids": [a.id for a in attachments]})
    else:
        record_event(db, run.id, "run.queued", "Agent run queued", {"agent_id": agent.id})
    db.commit()
    return run_out(run)


@router.get("/{agent_id}/runs", response_model=None, summary="Execution history")
def list_agent_runs(agent_id: str, status: str | None = None, page: Pagination = PageParams, db: Session = Depends(get_db)):
    _get_agent(db, agent_id)
    conditions = [AgentRun.agent_id == agent_id] + ([AgentRun.status == status] if status else [])
    total = db.scalar(select(func.count(AgentRun.id)).where(*conditions)) or 0
    rows = db.scalars(select(AgentRun).where(*conditions).order_by(AgentRun.created_at.desc()).limit(page.limit).offset(page.offset))
    return {"items": [run_out(r) for r in rows], "total": total, "limit": page.limit, "offset": page.offset}
