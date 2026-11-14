from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    __table_args__ = (Index("ix_agent_run_events_run_sequence", "run_id", "sequence"),)
