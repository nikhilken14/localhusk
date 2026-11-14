from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

from assistant.schemas.common import PatchModel


Status = Literal["todo", "in_progress", "done"]
Color = Literal["red", "yellow", "green"]


# ------------------------------------------------------------------
# Notes
# ------------------------------------------------------------------

class NoteIn(BaseModel):
    title: str = Field(default="Untitled note", min_length=1, max_length=240)
    content: str = ""
    color: Color = "yellow"
    pinned: bool = False

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class NotePatch(PatchModel):
    non_nullable: ClassVar[frozenset[str]] = frozenset(
        {"title", "content", "color", "pinned"}
    )

    title: str | None = Field(default=None, min_length=1, max_length=240)
    content: str | None = None
    color: Color | None = None
    pinned: bool | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    color: Color
    pinned: bool
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------

class TaskIn(BaseModel):
    task: str = Field(min_length=1, max_length=800)
    status: Status = "todo"
    due_at: datetime | None = None
    position: int | None = Field(default=None, ge=0)

    @field_validator("task")
    @classmethod
    def task_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("task must not be blank")
        return value


class TaskPatch(PatchModel):
    non_nullable: ClassVar[frozenset[str]] = frozenset(
        {"task", "status", "position"}
    )

    task: str | None = Field(default=None, min_length=1, max_length=800)
    status: Status | None = None
    # Explicit null clears the due date.
    due_at: datetime | None = None
    position: int | None = Field(default=None, ge=0)

    @field_validator("task")
    @classmethod
    def task_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("task must not be blank")
        return value


class TaskStatusIn(BaseModel):
    status: Status
    position: int | None = Field(default=None, ge=0)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task: str
    status: Status
    due_at: datetime | None
    position: int
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------
# Calendar events
# ------------------------------------------------------------------

class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = ""
    start_at: datetime
    end_at: datetime | None = None
    all_day: bool = False
    location: str = Field(default="", max_length=300)
    calendar_id: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value

    @model_validator(mode="after")
    def validate_event_times(self):
        from assistant.core.timeutil import ensure_utc
        start = ensure_utc(self.start_at)
        end = ensure_utc(self.end_at) if self.end_at is not None else None
        if end is not None and end < start:
            raise ValueError("end_at must not be before start_at")
        return self


class EventPatch(PatchModel):
    non_nullable: ClassVar[frozenset[str]] = frozenset(
        {"title", "description", "start_at", "all_day", "location"}
    )

    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool | None = None
    location: str | None = Field(default=None, max_length=300)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    calendar_id: str | None
    title: str
    description: str
    start_at: datetime
    end_at: datetime | None
    all_day: bool
    location: str
    source: str
    external_id: str | None
    read_only: bool = False
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------
# Calendars
# ------------------------------------------------------------------

class CalendarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    account_id: str | None
    account_email: str | None = None
    name: str
    color: str
    enabled: bool
    read_only: bool
    last_synced_at: datetime | None


class CalendarPatch(PatchModel):
    non_nullable: ClassVar[frozenset[str]] = frozenset(
        {"name", "color", "enabled"}
    )

    name: str | None = Field(default=None, min_length=1, max_length=200)
    color: str | None = Field(default=None, max_length=20)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class SyncRequest(BaseModel):
    account_id: str | None = None