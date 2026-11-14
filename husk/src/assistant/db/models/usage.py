from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


class UsageRecord(Base):
    """One LLM call.  Provider name/model are copied so history survives model deletion."""

    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_records_created_at", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider_id: Mapped[str | None] = mapped_column(String(36))
    provider_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    provider_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")  # chat | agent | test
    reference_id: Mapped[str | None] = mapped_column(String(36))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
