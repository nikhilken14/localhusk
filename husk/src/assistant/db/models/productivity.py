from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


class Note(Base):
    __tablename__ = "notes"

    __table_args__ = (
        Index("ix_notes_color_updated", "color", "updated_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    title: Mapped[str] = mapped_column(
        String(240),
        nullable=False,
        default="Untitled note",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    color: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default="yellow",
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class Task(Base):
    __tablename__ = "tasks"

    __table_args__ = (
        Index("ix_tasks_status_due", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    task: Mapped[str] = mapped_column(
        String(800),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="todo",
    )
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class Calendar(Base):
    __tablename__ = "calendars"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    provider: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="local",
    )  # local | google | microsoft
    account_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("mail_accounts.id", ondelete="CASCADE"),
    )
    external_id: Mapped[str | None] = mapped_column(String(400))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    color: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="#4f8cff",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    read_only: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    __table_args__ = (
        Index("ix_calendar_events_start", "start_at"),
        Index(
            "ix_calendar_events_calendar_external",
            "calendar_id",
            "external_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    calendar_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("calendars.id", ondelete="CASCADE"),
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
    )
    start_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
    )
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    all_day: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    location: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
        default="",
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="local",
    )
    external_id: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )