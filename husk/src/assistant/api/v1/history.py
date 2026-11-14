from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import PageParams, Pagination, get_db
from assistant.core.config import get_settings
from assistant.core.textutil import LIKE_ESCAPE, like_pattern, make_snippet, preview
from assistant.core.timeutil import ensure_utc
from assistant.db.models import ChatMessage, Conversation
from assistant.schemas.common import Page
from assistant.services import chat as chat_service
from assistant.services.maintenance import prune_history
from pydantic import BaseModel

router = APIRouter(prefix="/history", tags=["history"])


class HistoryMatch(BaseModel):
    message_id: str
    role: str
    snippet: str
    created_at: datetime


class HistoryItem(BaseModel):
    id: str
    title: str
    pinned: bool
    archived: bool
    message_count: int
    preview: str
    created_at: datetime
    updated_at: datetime
    matches: list[HistoryMatch] = []


@router.get("", response_model=Page[HistoryItem], summary="Search/filter conversation history")
def list_history(
    q: str | None = Query(None, description="Search titles and message text"),
    since: datetime | None = Query(None, description="Only conversations updated at/after this time"),
    until: datetime | None = None,
    days: int | None = Query(None, ge=1, le=3650, description="Window length; defaults to HISTORY_RETENTION_DAYS (5)"),
    all: bool = Query(False, description="Ignore the default window and return everything"),
    role: str | None = Query(None, pattern="^(user|assistant)$", description="Restrict message matches to a role"),
    page: Pagination = PageParams, db: Session = Depends(get_db),
):
    """Read-only.  When neither ``since`` nor ``all`` is given, only the last five days are returned
    (the window is configurable); nothing is ever deleted by this endpoint."""
    if since is None and not all:
        since = chat_service.window_start(days or get_settings().history_retention_days)
    conditions = []
    if since:
        conditions.append(Conversation.updated_at >= ensure_utc(since))
    if until:
        conditions.append(Conversation.updated_at < ensure_utc(until))
    pattern = like_pattern(q) if q and q.strip() else None
    if pattern:
        message_match = and_(ChatMessage.conversation_id == Conversation.id, ChatMessage.content.ilike(pattern, escape=LIKE_ESCAPE))
        if role:
            message_match = and_(message_match, ChatMessage.role == role)
        conditions.append(or_(Conversation.title.ilike(pattern, escape=LIKE_ESCAPE), exists().where(message_match)))
    total = db.scalar(select(func.count(Conversation.id)).where(*conditions)) or 0
    conversations = db.scalars(select(Conversation).where(*conditions).order_by(Conversation.updated_at.desc())
                               .limit(page.limit).offset(page.offset)).all()
    ids = [c.id for c in conversations]
    counts = chat_service.message_counts(db, ids)
    matches: dict[str, list[HistoryMatch]] = {cid: [] for cid in ids}
    if pattern and ids:
        stmt = select(ChatMessage).where(ChatMessage.conversation_id.in_(ids), ChatMessage.content.ilike(pattern, escape=LIKE_ESCAPE))
        if role:
            stmt = stmt.where(ChatMessage.role == role)
        for message in db.scalars(stmt.order_by(ChatMessage.created_at.desc())):
            if len(matches[message.conversation_id]) < 3:  # a few hits per conversation is enough for a result list
                matches[message.conversation_id].append(HistoryMatch(
                    message_id=message.id, role=message.role, snippet=make_snippet(message.content, q), created_at=message.created_at))
    previews = {}
    if ids:
        for cid in ids:
            previews[cid] = db.scalar(select(ChatMessage.content).where(ChatMessage.conversation_id == cid)
                                      .order_by(ChatMessage.created_at.desc()).limit(1)) or ""
    items = [HistoryItem(id=c.id, title=c.title, pinned=c.pinned, archived=c.archived, message_count=counts.get(c.id, 0),
                         preview=preview(previews.get(c.id, "")), created_at=c.created_at, updated_at=c.updated_at,
                         matches=matches[c.id]) for c in conversations]
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/prune", summary="Permanently delete conversations older than N days")
def prune(days: int | None = Query(None, ge=1, le=3650), db: Session = Depends(get_db)):
    return {"deleted_conversations": prune_history(db, days or get_settings().history_retention_days)}
