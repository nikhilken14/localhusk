from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


class ProviderConfig(Base):
    """An LLM model connection.  API keys live in the OS keyring, never in this table."""

    __tablename__ = "provider_configs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(300))
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_test_error: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
