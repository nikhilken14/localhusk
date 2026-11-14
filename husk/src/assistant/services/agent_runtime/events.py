"""Durable, per-run event log used for UI progress polling."""
from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from assistant.db.models import AgentRun, AgentRunEvent


def record_event(db: Session, run_id: str, event_type: str, message: str, details: dict | None = None) -> AgentRunEvent:
    """Append an event.  The sequence comes from an atomic counter on the run row, so concurrent
    writers (API thread + worker thread) cannot hand out the same number."""
    bumped = db.execute(
        update(AgentRun).where(AgentRun.id == run_id).values(event_seq=AgentRun.event_seq + 1)
        .execution_options(synchronize_session=False)
    )
    if bumped.rowcount:
        sequence = db.scalar(select(AgentRun.event_seq).where(AgentRun.id == run_id)) or 1
    else:  # run row missing (shouldn't happen) - fall back to max()+1
        from sqlalchemy import func
        sequence = (db.scalar(select(func.max(AgentRunEvent.sequence)).where(AgentRunEvent.run_id == run_id)) or 0) + 1
    event = AgentRunEvent(run_id=run_id, sequence=sequence, event_type=event_type, message=message[:500],
                          details_json=json.dumps(details or {}, default=str))
    db.add(event)
    return event


def event_out(event: AgentRunEvent) -> dict:
    try:
        details = json.loads(event.details_json or "{}")
    except (TypeError, json.JSONDecodeError):
        details = {}
    return {"id": event.id, "run_id": event.run_id, "sequence": event.sequence, "type": event.event_type,
            "message": event.message, "details": details, "created_at": event.created_at}
