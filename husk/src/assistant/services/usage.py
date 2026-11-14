from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistant.core.textutil import estimate_tokens
from assistant.db.models import ProviderConfig, UsageRecord
from assistant.providers.base import ChatMessageInput, Usage


def record_usage(db: Session, provider: ProviderConfig, *, source: str,
                 usage: Usage | None, messages: list[ChatMessageInput] | None = None,
                 output_text: str = "", reference_id: str | None = None) -> UsageRecord:
    """Store token counts, falling back to a rough estimate when the provider reports none."""
    usage = usage or Usage()
    estimated = usage.input_tokens is None or usage.output_tokens is None
    input_tokens = usage.input_tokens if usage.input_tokens is not None else sum(
        estimate_tokens(m.content) for m in (messages or []))
    output_tokens = usage.output_tokens if usage.output_tokens is not None else (
        estimate_tokens(output_text) if output_text else 0)
    row = UsageRecord(
        provider_id=provider.id, provider_name=provider.name, provider_kind=provider.kind, model=provider.model,
        source=source, reference_id=reference_id, input_tokens=int(input_tokens), output_tokens=int(output_tokens),
        estimated=estimated,
    )
    db.add(row)
    return row


def totals(db: Session, since: datetime, until: datetime | None = None) -> dict:
    stmt = select(
        func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.input_tokens), 0),
        func.coalesce(func.sum(UsageRecord.output_tokens), 0),
    ).where(UsageRecord.created_at >= since)
    if until:
        stmt = stmt.where(UsageRecord.created_at < until)
    requests, input_tokens, output_tokens = db.execute(stmt).one()
    return {"requests": int(requests), "input_tokens": int(input_tokens), "output_tokens": int(output_tokens),
            "total_tokens": int(input_tokens) + int(output_tokens)}
