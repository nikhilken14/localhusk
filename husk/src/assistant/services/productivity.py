"""Shared productivity helpers for API routes and agent tools."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from assistant.core.timeutil import utcnow
from assistant.db.models import Calendar, CalendarEvent, Note, Task


NOTE_COLORS = {"red", "yellow", "green"}
TASK_STATUSES = {"todo", "in_progress", "done"}


def local_calendar(db: Session) -> Calendar:
    """Return the existing local calendar or create it."""
    calendar = db.scalar(
        select(Calendar)
        .where(Calendar.provider == "local")
        .order_by(Calendar.created_at)
        .limit(1)
    )

    if calendar is None:
        calendar = Calendar(
            provider="local",
            name="Local",
            color="#4f8cff",
            read_only=False,
        )
        db.add(calendar)
        db.flush()

    return calendar


# ------------------------------------------------------------------
# Notes
# ------------------------------------------------------------------

def create_note(
    db: Session,
    *,
    title: str = "Untitled note",
    content: str = "",
    color: str = "yellow",
    pinned: bool = False,
) -> Note:
    title = title.strip()

    if not title:
        raise ValueError("Note title cannot be empty")

    # Be defensive when called by tools or other non-API callers.
    color = color or "yellow"
    if color not in NOTE_COLORS:
        raise ValueError(f"Invalid note color: {color}")

    note = Note(
        title=title,
        content=content,
        color=color,
        pinned=pinned,
    )
    db.add(note)
    db.flush()
    return note


def update_note(note: Note, *, changes: dict) -> Note:
    """Update explicitly supplied, validated note fields."""
    allowed = {"title", "content", "color", "pinned"}

    for key, value in changes.items():
        if key not in allowed:
            raise ValueError(f"Unsupported note field: {key}")

        if value is None:
            raise ValueError(f"{key} cannot be null")

        if key == "title":
            value = value.strip()
            if not value:
                raise ValueError("Note title cannot be empty")

        if key == "color" and value not in NOTE_COLORS:
            raise ValueError(f"Invalid note color: {value}")

        setattr(note, key, value)

    note.updated_at = utcnow()
    return note


def note_ordering():
    """Pinned first, then red, yellow, green, newest updated first."""
    color_rank = case(
        (Note.color == "red", 0),
        (Note.color == "yellow", 1),
        (Note.color == "green", 2),
        else_=3,
    )

    return (
        Note.pinned.desc(),
        color_rank,
        Note.updated_at.desc(),
        Note.id,
    )


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------

def next_task_position(db: Session, status: str) -> int:
    if status not in TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")

    highest = db.scalar(
        select(func.max(Task.position)).where(Task.status == status)
    )

    return 0 if highest is None else int(highest) + 1


def create_task(
    db: Session,
    *,
    task: str,
    status: str = "todo",
    due_at: datetime | None = None,
    position: int | None = None,
) -> Task:
    if status not in TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")

    task_text = task.strip()
    if not task_text:
        raise ValueError("Task cannot be empty")

    requested_position = position

    if requested_position is None:
        requested_position = next_task_position(db, status)

    record = Task(
        task=task_text,
        status=status,
        due_at=due_at,
        position=requested_position,
        completed_at=utcnow() if status == "done" else None,
    )

    db.add(record)
    db.flush()

    # Normalize the column and insert at the requested position.
    if position is not None:
        apply_task_status(db, record, status, position)

    return record


def apply_task_status(
    db: Session,
    task: Task,
    status: str,
    position: int | None = None,
) -> str:
    """
    Move a task to a Kanban column and normalize positions.

    Positions are zero-based. If position is omitted, a moved task
    is appended to the destination column.
    """
    if status not in TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")

    if position is not None and position < 0:
        raise ValueError("Task position cannot be negative")

    previous_status = task.status

    if previous_status == status and position is None:
        # Still repair the completion timestamp if necessary.
        expected_completed_at = (
            task.completed_at if status == "done" else None
        )
        if status != "done" and task.completed_at is not None:
            task.completed_at = None
            task.updated_at = utcnow()
        elif status == "done" and expected_completed_at is None:
            task.completed_at = utcnow()
            task.updated_at = utcnow()

        return previous_status

    destination = list(
        db.scalars(
            select(Task)
            .where(Task.status == status, Task.id != task.id)
            .order_by(Task.position, Task.created_at, Task.id)
        ).all()
    )

    if previous_status != status:
        source = list(
            db.scalars(
                select(Task)
                .where(
                    Task.status == previous_status,
                    Task.id != task.id,
                )
                .order_by(Task.position, Task.created_at, Task.id)
            ).all()
        )

        for index, item in enumerate(source):
            item.position = index

    insert_at = (
        len(destination)
        if position is None
        else min(position, len(destination))
    )
    destination.insert(insert_at, task)

    task.status = status
    task.completed_at = utcnow() if status == "done" else None
    task.updated_at = utcnow()

    # Persist status changes before normalizing destination positions.
    db.flush()

    for index, item in enumerate(destination):
        item.position = index

    db.flush()
    return previous_status


def update_task(task: Task, *, changes: dict) -> Task:
    """Update task text or due date without moving its Kanban column."""
    allowed = {"task", "due_at"}

    for key, value in changes.items():
        if key not in allowed:
            raise ValueError(f"Unsupported task field: {key}")

        if key == "task":
            if value is None:
                raise ValueError("Task cannot be null")

            value = value.strip()
            if not value:
                raise ValueError("Task cannot be empty")

        setattr(task, key, value)

    task.updated_at = utcnow()
    return task


# ------------------------------------------------------------------
# Calendar events
# ------------------------------------------------------------------

def create_event(
    db: Session,
    *,
    title: str,
    start_at: datetime,
    end_at: datetime | None = None,
    description: str = "",
    location: str = "",
    all_day: bool = False,
    calendar_id: str | None = None,
) -> CalendarEvent:
    if end_at is not None and end_at < start_at:
        raise ValueError("end_at must not be before start_at")

    if not title.strip():
        raise ValueError("Event title cannot be empty")

    if calendar_id is None:
        calendar = local_calendar(db)
    else:
        calendar = db.get(Calendar, calendar_id)
        if calendar is None:
            raise ValueError("Calendar not found")

    event = CalendarEvent(
        calendar_id=calendar.id,
        title=title.strip(),
        description=description,
        start_at=start_at,
        end_at=end_at,
        location=location,
        all_day=all_day,
        source="local",
    )

    db.add(event)
    db.flush()
    return event