from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.timeutil import ensure_utc, utcnow
from assistant.db.models import ProviderConfig, UsageRecord
from assistant.services import llm
from assistant.services.usage import totals

router = APIRouter(prefix="/usage", tags=["usage"])


def _connectivity(p: ProviderConfig | None) -> dict | None:
    if p is None:
        return None
    status = "unknown" if p.last_test_ok is None else ("connected" if p.last_test_ok else "error")
    return {"id": p.id, "name": p.name, "kind": p.kind, "model": p.model, "is_default": p.is_default, "status": status,
            "latency_ms": p.last_test_latency_ms, "checked_at": p.last_test_at, "error": p.last_test_error}


@router.get("/today")
def usage_today(since: datetime | None = Query(None, description="ISO start of 'today' in the client's zone; default 00:00 UTC"),
                db: Session = Depends(get_db)):
    now = utcnow()
    start = ensure_utc(since) or now.replace(hour=0, minute=0, second=0, microsecond=0)
    models = [_connectivity(p) for p in db.scalars(select(ProviderConfig).order_by(ProviderConfig.created_at))]
    return {"since": start, **totals(db, start), "default_model": _connectivity(llm.get_default_provider(db)), "models": models}


@router.get("/summary")
def usage_summary(group_by: Literal["day", "provider", "model"] = "day", since: datetime | None = None,
                  until: datetime | None = None, db: Session = Depends(get_db)):
    key = {"day": func.date(UsageRecord.created_at), "provider": UsageRecord.provider_name, "model": UsageRecord.model}[group_by]
    stmt = select(key.label("key"), func.count(UsageRecord.id), func.sum(UsageRecord.input_tokens),
                  func.sum(UsageRecord.output_tokens)).group_by(key).order_by(key)
    if since:
        stmt = stmt.where(UsageRecord.created_at >= ensure_utc(since))
    if until:
        stmt = stmt.where(UsageRecord.created_at < ensure_utc(until))
    rows = [{"key": str(k), "requests": int(r), "input_tokens": int(i or 0), "output_tokens": int(o or 0),
             "total_tokens": int(i or 0) + int(o or 0)} for k, r, i, o in db.execute(stmt)]
    return {"group_by": group_by, "rows": rows}
