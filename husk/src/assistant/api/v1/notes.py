"""Notes API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.api.dependencies import get_db
from assistant.core.errors import APIError
from assistant.core.textutil import LIKE_ESCAPE, like_pattern
from assistant.db.models import Note
from assistant.schemas.productivity import (
    Color,
    NoteIn,
    NoteOut,
    NotePatch,
)
from assistant.services import productivity as prod
from assistant.services.automation import fire_event


router = APIRouter(prefix="/notes", tags=["notes"])


def _get(db: Session, note_id: str) -> Note:
    note = db.get(Note, note_id)
    if note is None:
        raise APIError(404, "Note not found")
    return note


def _payload(note: Note) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "color": note.color,
        "pinned": note.pinned,
    }


@router.get(
    "",
    response_model=list[NoteOut],
    summary="List notes by pin state, importance, and update time",
)
def list_notes(
    q: str | None = None,
    color: Color | None = None,
    pinned: bool | None = None,
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    stmt = select(Note)

    if q and q.strip():
        pattern = like_pattern(q.strip())
        stmt = stmt.where(
            Note.title.ilike(pattern, escape=LIKE_ESCAPE)
            | Note.content.ilike(pattern, escape=LIKE_ESCAPE)
        )

    if color is not None:
        stmt = stmt.where(Note.color == color)

    if pinned is not None:
        stmt = stmt.where(Note.pinned.is_(pinned))

    stmt = stmt.order_by(*prod.note_ordering()).limit(limit)
    return db.scalars(stmt).all()


@router.post("", response_model=NoteOut, status_code=201)
def create_note(
    payload: NoteIn,
    db: Session = Depends(get_db),
):
    note = prod.create_note(
        db,
        title=payload.title,
        content=payload.content,
        color=payload.color,
        pinned=payload.pinned,
    )

    fire_event(db, "note.created", _payload(note))

    db.commit()
    db.refresh(note)
    return note


@router.get("/{note_id}", response_model=NoteOut)
def get_note(
    note_id: str,
    db: Session = Depends(get_db),
):
    return _get(db, note_id)


@router.put(
    "/{note_id}",
    response_model=NoteOut,
    summary="Replace note content and metadata",
)
def replace_note(
    note_id: str,
    payload: NoteIn,
    db: Session = Depends(get_db),
):
    note = _get(db, note_id)

    prod.update_note(
        note,
        changes={
            "title": payload.title,
            "content": payload.content,
            "color": payload.color,
            "pinned": payload.pinned,
        },
    )

    fire_event(db, "note.updated", _payload(note))

    db.commit()
    db.refresh(note)
    return note


@router.patch("/{note_id}", response_model=NoteOut)
def patch_note(
    note_id: str,
    payload: NotePatch,
    db: Session = Depends(get_db),
):
    note = _get(db, note_id)
    changes = payload.model_dump(exclude_unset=True)

    prod.update_note(note, changes=changes)

    fire_event(db, "note.updated", _payload(note))

    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=204)
def delete_note(
    note_id: str,
    db: Session = Depends(get_db),
) -> Response:
    note = _get(db, note_id)

    db.delete(note)
    db.commit()

    return Response(status_code=204)