"""Background agent worker.

One run at a time.  All database and blocking-HTTP work runs in a thread so the event loop (and
therefore the API) stays responsive; only the LLM planning call is awaited on the loop.

Lifecycle: queued -> running -> (awaiting_approval -> queued -> running)* -> completed | failed
           | cancelled | deferred.  ``deferred`` means the LLM was unreachable; the worker requeues
those runs once a provider is available again.  Resuming after an approval re-enters ``execute_run``
and continues from the first step that has no recorded result.
"""
from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from datetime import timedelta

from assistant.core.timeutil import ensure_utc, utcnow
from assistant.db.models import Agent, AgentApproval, AgentRun
from assistant.db.session import SessionLocal
from assistant.providers.base import ChatMessageInput
from assistant.providers.registry import registry
from assistant.services import llm
from assistant.services.agent_runtime import tools
from assistant.services.agent_runtime.events import record_event
from assistant.services.agent_runtime.planner import build_planner_prompt, validate_plan
from assistant.services.automation import fire_event
from assistant.services.usage import record_usage

log = logging.getLogger("assistant.agent.worker")


class PlanningError(RuntimeError):
    pass


class TransientLLMError(PlanningError):
    """LLM / provider temporarily unavailable — run should be deferred and retried."""


# Substrings / codes that indicate the model is offline or misconfigured rather than a bad plan.
_TRANSIENT_MARKERS = (
    "llm request failed",
    "llm planning failed",
    "connection",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "service unavailable",
    "502",
    "503",
    "504",
    "connecterror",
    "network",
    "unreachable",
    "no_default_model",
    "configure an llm",
    "secret_store_unavailable",
    "api key",
    "authentication",
    "unauthorized",
    "401",
    "429",  # rate limit — worth retrying
)


def _is_transient_llm_failure(message: str) -> bool:
    lower = (message or "").lower()
    return any(m in lower for m in _TRANSIENT_MARKERS)


def _state(run: AgentRun) -> dict:
    try:
        data = json.loads(run.result or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_state(run: AgentRun, completed: list, total: int, **extra) -> None:
    run.result = json.dumps({"completed_steps": completed, "total_steps": total, **extra}, default=str)


def _finish(db: Session, run: AgentRun, status: str, error: str = "") -> None:
    run.status, run.error, run.finished_at = status, error[:1000], utcnow()
    if status == "failed":
        record_event(db, run.id, "run.failed", error or "Run failed")
        if run.trigger != "event":  # don't let a failing event-triggered job re-trigger itself forever
            fire_event(db, "agent.run_failed", {"run_id": run.id, "agent_id": run.agent_id, "error": error[:300]})
        log.warning("Agent run %s failed: %s", run.id, error, extra={"category": "agent"})
    elif status == "completed":
        record_event(db, run.id, "run.completed", "Agent run completed")
    db.commit()


def recover_interrupted_runs() -> int:
    """A crash mid-step may have half-applied a write, so don't blindly resume: fail those runs."""
    with SessionLocal() as db:
        stuck = db.scalars(select(AgentRun).where(AgentRun.status == "running")).all()
        for run in stuck:
            _finish(db, run, "failed", "Interrupted by application restart")
        return len(stuck)


def claim_next_run() -> str | None:
    with SessionLocal() as db:
        run_id = db.scalar(select(AgentRun.id).where(AgentRun.status == "queued").order_by(AgentRun.created_at).limit(1))
        if run_id is None:
            return None
        claimed = db.execute(
            update(AgentRun).where(AgentRun.id == run_id, AgentRun.status == "queued").values(status="running")
            .execution_options(synchronize_session=False)
        )
        if not claimed.rowcount:
            db.rollback()
            return None
        run = db.get(AgentRun, run_id)
        resumed = run.started_at is not None
        if not resumed:
            run.started_at = utcnow()
        record_event(db, run.id, "run.resumed" if resumed else "run.started",
                     "Agent run resumed" if resumed else "Agent run started")
        db.commit()
        return run_id


def _planning_inputs(run_id: str):
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        agent = db.get(Agent, run.agent_id) if run.agent_id else None
        provider = llm.snapshot(llm.resolve_provider(db, agent.provider_id if agent else None))
        tool_ids = json.loads(agent.tools_json) if agent else None
        allowed = tools.allowed_tools(db, tool_ids)
        return provider, allowed, run.goal, (agent.system_prompt if agent else "")


async def _plan(run_id: str) -> dict:
    try:
        provider, allowed, goal, instructions = await asyncio.to_thread(_planning_inputs, run_id)
    except Exception as exc:  # noqa: BLE001 - includes APIError for "no default model"
        raise PlanningError(getattr(exc, "message", None) or str(exc)) from exc
    if not allowed:
        raise PlanningError("This agent has no available tools")
    messages = [ChatMessageInput("user", build_planner_prompt(goal, allowed, instructions))]
    try:
        completion = await registry.get(provider.kind).complete(
            messages, provider.options(min(provider.temperature, 0.2), cap_tokens=1500), provider.api_key, provider.base_url)
    except Exception as exc:  # noqa: BLE001
        raise PlanningError(f"LLM planning failed: {llm.safe_error(exc, provider.api_key)}") from exc

    def store_usage() -> None:
        with SessionLocal() as db:
            row = record_usage(db, provider, source="agent", usage=completion.usage, messages=messages,
                               output_text=completion.text, reference_id=run_id)
            run = db.get(AgentRun, run_id)
            run.input_tokens = (run.input_tokens or 0) + row.input_tokens
            run.output_tokens = (run.output_tokens or 0) + row.output_tokens
            db.commit()
    await asyncio.to_thread(store_usage)
    try:
        return validate_plan(completion.text, allowed)
    except ValueError as exc:
        raise PlanningError(f"Planner returned an invalid plan: {exc}") from exc


def _save_plan(run_id: str, plan: dict) -> None:
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        run.plan_json = json.dumps(plan)
        record_event(db, run.id, "plan.created", f"Plan created with {len(plan['steps'])} step(s)",
                     {"steps": [s["tool"] for s in plan["steps"]], "explanation": plan.get("explanation", "")})
        db.commit()


def _fail(run_id: str, message: str) -> None:
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        if run and run.status == "running":
            _finish(db, run, "failed", message)


# Cap retries so a permanently broken LLM does not spin forever.
MAX_DEFER_RETRIES = 8
# Backoff: 60s * 2^retry_count, capped at 1 hour.
_BACKOFF_BASE_SECONDS = 60
_BACKOFF_MAX_SECONDS = 3600


def _backoff_seconds(retry_count: int) -> int:
    return min(_BACKOFF_BASE_SECONDS * (2 ** max(0, retry_count)), _BACKOFF_MAX_SECONDS)


def _defer(run_id: str, message: str) -> None:
    """Park a run until the LLM is reachable again (status=deferred), with exponential backoff.

    After MAX_DEFER_RETRIES deferred attempts the run is failed permanently.
    """
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        if run is None or run.status not in ("running", "queued", "deferred"):
            return
        attempt = int(run.retry_count or 0) + 1
        run.retry_count = attempt
        reason = (message or "LLM unavailable")[:1000]
        if attempt > MAX_DEFER_RETRIES:
            _finish(
                db,
                run,
                "failed",
                f"Gave up after {MAX_DEFER_RETRIES} deferred retries. Last error: {reason}",
            )
            return
        delay = _backoff_seconds(attempt - 1)
        run.status = "deferred"
        run.error = reason
        run.finished_at = None
        run.next_retry_at = utcnow() + timedelta(seconds=delay)
        record_event(
            db,
            run.id,
            "run.deferred",
            f"Deferred (attempt {attempt}/{MAX_DEFER_RETRIES}); retry in {delay}s",
            {"reason": reason[:300], "retry_count": attempt, "next_retry_at": run.next_retry_at.isoformat()},
        )
        db.commit()
        log.info(
            "Agent run %s deferred attempt %s/%s (retry in %ss): %s",
            run_id, attempt, MAX_DEFER_RETRIES, delay, reason[:200],
            extra={"category": "agent"},
        )


def requeue_deferred_runs(limit: int = 20) -> int:
    """Move due deferred runs back to queued when a usable LLM provider exists.

    Respects next_retry_at (exponential backoff). Returns how many runs were requeued.
    """
    from assistant.services import llm as llm_service

    now = utcnow()
    with SessionLocal() as db:
        try:
            llm_service.resolve_provider(db, None)
        except Exception:  # noqa: BLE001 - still no usable model
            return 0
        rows = db.scalars(
            select(AgentRun)
            .where(
                AgentRun.status == "deferred",
                (AgentRun.next_retry_at.is_(None)) | (AgentRun.next_retry_at <= now),
            )
            .order_by(AgentRun.created_at)
            .limit(limit)
        ).all()
        if not rows:
            return 0
        for run in rows:
            run.status = "queued"
            run.error = ""
            # Keep retry_count so the next defer continues the backoff sequence.
            record_event(
                db,
                run.id,
                "run.requeued",
                f"Requeued after backoff (attempt {run.retry_count}/{MAX_DEFER_RETRIES})",
                {"retry_count": run.retry_count},
            )
        db.commit()
        log.info("Requeued %s deferred agent run(s)", len(rows), extra={"category": "agent"})
        return len(rows)


def _needs_plan(run_id: str) -> bool | None:
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        return None if run is None else run.plan_json is None


def execute_run(run_id: str) -> None:
    """Execute remaining plan steps (blocking).  Stops at approval gates and on cancellation."""
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        if run is None or run.status != "running":
            return
        try:
            steps = json.loads(run.plan_json or "{}").get("steps", [])
            completed = list(_state(run).get("completed_steps", []))
            if len(completed) > len(steps):
                completed = []
            for index in range(len(completed), len(steps)):
                db.refresh(run)
                if run.status != "running":
                    return  # cancelled (or otherwise changed) between steps
                tool_id, args = steps[index]["tool"], steps[index]["arguments"]
                entry = tools.get_tool(db, tool_id)
                approval = None
                if entry is not None and entry["requires_approval"]:
                    approval = db.scalar(select(AgentApproval).where(
                        AgentApproval.run_id == run.id, AgentApproval.step_index == index
                    ).order_by(AgentApproval.created_at.desc()).limit(1))
                    if approval is None:
                        approval = AgentApproval(run_id=run.id, step_index=index, action=tool_id,
                                                 details=json.dumps({"arguments": args}))
                        db.add(approval)
                        db.flush()
                    if approval.status == "pending":
                        run.status = "awaiting_approval"
                        _save_state(run, completed, len(steps), pending_step=index, approval_required=True)
                        record_event(db, run.id, "approval.required", "Approval required before this action can run",
                                     {"step": index, "tool": tool_id, "approval_id": approval.id})
                        fire_event(db, "approval.requested", {"approval_id": approval.id, "run_id": run.id, "tool": tool_id})
                        db.commit()
                        return
                    if approval.status == "rejected":
                        _finish(db, run, "failed", "Required action was rejected")
                        return
                record_event(db, run.id, "step.started", f"Step {index + 1} started", {"step": index, "tool": tool_id})
                result = tools.execute_tool(db, tool_id, args)
                if approval is not None:
                    approval.status = "executed"
                completed.append({"step": index, "tool": tool_id, "result": result})
                _save_state(run, completed, len(steps))
                record_event(db, run.id, "step.completed", f"Step {index + 1} completed", {"step": index, "tool": tool_id})
                db.commit()
            db.refresh(run)
            if run.status == "running":
                _save_state(run, completed, len(steps))
                if not steps:
                    # Empty plan is often intentional ("nothing to do" / pure Q&A). Prefer
                    # completing with the planner's explanation instead of hard-failing.
                    explanation = ""
                    try:
                        plan = json.loads(run.plan_json or "{}")
                        explanation = (plan.get("explanation") or "").strip()
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass
                    if explanation:
                        run.result = explanation[:8000]
                        _finish(db, run, "completed")
                    else:
                        _finish(
                            db, run, "failed",
                            "The planner returned no tool steps. Rephrase the goal or check the agent's allowed tools.",
                        )
                else:
                    _finish(db, run, "completed")
        except tools.ToolError as exc:
            db.rollback()
            run = db.get(AgentRun, run_id)
            if run is not None and run.status != "cancelled":
                _finish(db, run, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.exception("Agent run %s crashed", run_id, extra={"category": "agent"})
            run = db.get(AgentRun, run_id)
            if run is not None and run.status != "cancelled":
                _finish(db, run, "failed", f"Execution failed: {type(exc).__name__}")


async def process_run(run_id: str) -> None:
    needs_plan = await asyncio.to_thread(_needs_plan, run_id)
    if needs_plan is None:
        return
    if needs_plan:
        try:
            plan = await _plan(run_id)
        except PlanningError as exc:
            message = str(exc)
            if _is_transient_llm_failure(message):
                await asyncio.to_thread(_defer, run_id, message)
            else:
                await asyncio.to_thread(_fail, run_id, message)
            return
        await asyncio.to_thread(_save_plan, run_id, plan)
    await asyncio.to_thread(execute_run, run_id)


async def agent_worker_loop(stop_event: asyncio.Event, poll_seconds: float = 2.0) -> None:
    await asyncio.to_thread(recover_interrupted_runs)
    ticks = 0
    while not stop_event.is_set():
        try:
            # Every ~15s try to promote deferred runs if the LLM is back.
            ticks += 1
            if ticks % max(1, int(15 / max(poll_seconds, 0.5))) == 0:
                await asyncio.to_thread(requeue_deferred_runs)
            run_id = await asyncio.to_thread(claim_next_run)
            if run_id:
                await process_run(run_id)
                continue
        except Exception:  # noqa: BLE001
            log.exception("Agent worker iteration failed", extra={"category": "agent"})
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
        except asyncio.TimeoutError:
            pass
