from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.errors import APIError
from assistant.core.textutil import LIKE_ESCAPE, like_pattern
from assistant.core.timeutil import ensure_utc
from assistant.db.models import Calendar, CalendarEvent, MailAccount
from assistant.schemas.productivity import (
    CalendarOut, CalendarPatch, EventIn, EventOut, EventPatch, SyncRequest,
)
from assistant.services import productivity as prod
from assistant.services.automation import fire_event
from assistant.services.calendar_sync import sync_calendars

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _event_out(event: CalendarEvent) -> EventOut:
    out = EventOut.model_validate(event)
    out.read_only = event.source != "local"
    return out


def _get(db: Session, event_id: str) -> CalendarEvent:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise APIError(404, "Calendar event not found")
    return event


def _require_local(event: CalendarEvent) -> None:
    if event.source != "local":
        raise APIError(409, "Only local calendar events can be edited. Provider-synced events are read-only.", "read_only_event")


@router.get("/events", response_model=list[EventOut], summary="Events overlapping [start, end)")
def list_events(start: datetime | None = None, end: datetime | None = None, calendar_id: str | None = None,
                q: str | None = None, limit: int = Query(1000, ge=1, le=5000), db: Session = Depends(get_db)):
    stmt = select(CalendarEvent).join(Calendar, CalendarEvent.calendar_id == Calendar.id, isouter=True)
    stmt = stmt.where((Calendar.id.is_(None)) | (Calendar.enabled.is_(True)))
    if start:
        stmt = stmt.where(func.coalesce(CalendarEvent.end_at, CalendarEvent.start_at) >= ensure_utc(start))
    if end:
        stmt = stmt.where(CalendarEvent.start_at < ensure_utc(end))
    if calendar_id:
        stmt = stmt.where(CalendarEvent.calendar_id == calendar_id)
    if q and q.strip():
        pattern = like_pattern(q)
        stmt = stmt.where(CalendarEvent.title.ilike(pattern, escape=LIKE_ESCAPE) | CalendarEvent.location.ilike(pattern, escape=LIKE_ESCAPE))
    return [_event_out(e) for e in db.scalars(stmt.order_by(CalendarEvent.start_at).limit(limit))]


@router.post("/events", response_model=EventOut, status_code=201)
def create_event(payload: EventIn, db: Session = Depends(get_db)):
    calendar_id = payload.calendar_id
    if calendar_id:
        cal = db.get(Calendar, calendar_id)
        if cal is None:
            raise APIError(404, "Calendar not found")
        if cal.read_only:
            raise APIError(409, "That calendar is read-only", "read_only_calendar")
    event = prod.create_event(db, title=payload.title.strip(), start_at=payload.start_at, end_at=payload.end_at,
                              description=payload.description, location=payload.location, all_day=payload.all_day,
                              calendar_id=calendar_id)
    fire_event(db, "calendar.event_created", {"id": event.id, "title": event.title, "start_at": event.start_at,
                                              "end_at": event.end_at, "location": event.location})
    db.commit()
    return _event_out(event)


@router.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: str, db: Session = Depends(get_db)):
    return _event_out(_get(db, event_id))


@router.patch("/events/{event_id}", response_model=EventOut)
def update_event(event_id: str, payload: EventPatch, db: Session = Depends(get_db)):
    event = _get(db, event_id)
    _require_local(event)
    from assistant.core.timeutil import ensure_utc
    changes = payload.model_dump(exclude_unset=True)
    for key in ("start_at", "end_at"):
        if key in changes and changes[key] is not None:
            changes[key] = ensure_utc(changes[key])
    for key, value in changes.items():
        setattr(event, key, value)
    if event.end_at and ensure_utc(event.end_at) < ensure_utc(event.start_at):
        raise APIError(422, "end_at must not be before start_at", "validation_error")
    db.commit()
    return _event_out(event)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, db: Session = Depends(get_db)):
    event = _get(db, event_id)
    _require_local(event)
    db.delete(event)
    db.commit()


@router.get("/calendars", response_model=list[CalendarOut], summary="Local workspace calendar (provider calendars are no longer synced)")
def list_calendars(db: Session = Depends(get_db)):
    # Calendar is local-only: ensure the workspace calendar exists and only return local calendars.
    prod.local_calendar(db)
    db.commit()
    out = []
    for cal in db.scalars(select(Calendar).where(Calendar.provider == "local").order_by(Calendar.name)):
        item = CalendarOut.model_validate(cal)
        out.append(item)
    return out


@router.patch("/calendars/{calendar_id}", response_model=CalendarOut, summary="Rename, recolor, or hide a calendar")
def update_calendar(calendar_id: str, payload: CalendarPatch, db: Session = Depends(get_db)):
    cal = db.get(Calendar, calendar_id)
    if cal is None:
        raise APIError(404, "Calendar not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if cal.provider != "local" and key == "name":
            continue  # provider-owned names are refreshed on each sync
        setattr(cal, key, value)
    db.commit()
    return CalendarOut.model_validate(cal)


@router.post("/sync", summary="Local calendar only — no provider sync")
def sync(payload: SyncRequest | None = None, db: Session = Depends(get_db)):
    # Calendar is local-only. Ensure the local calendar exists; do not call provider APIs.
    prod.local_calendar(db)
    db.commit()
    return {
        "synced": [],
        "message": "Calendar is local-only. Events are stored on this device; provider calendar sync is disabled.",
    }
