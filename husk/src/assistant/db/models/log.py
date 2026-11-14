from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


class AppLog(Base):
    __tablename__ = "app_logs"
    __table_args__ = (
        Index("ix_app_logs_created_at", "created_at"),
        Index("ix_app_logs_category_level", "category", "level"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="system")
    logger: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
