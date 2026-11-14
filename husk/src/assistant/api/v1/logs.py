from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import PageParams, Pagination, get_db
from assistant.core.logging import CATEGORIES
from assistant.core.textutil import LIKE_ESCAPE, like_pattern
from assistant.core.timeutil import ensure_utc
from assistant.db.models import AppLog
from assistant.schemas.common import Page

router = APIRouter(prefix="/logs", tags=["logs"])
LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogOut(BaseModel):
    id: int
    created_at: datetime
    level: str
    category: str
    logger: str
    message: str
    details: dict


@router.get("", response_model=Page[LogOut])
def list_logs(category: str | None = Query(None, description=f"One of {', '.join(CATEGORIES)}"),
              level: str | None = Query(None, description="Minimum level (DEBUG..CRITICAL)"),
              q: str | None = None, since: datetime | None = None, until: datetime | None = None,
              page: Pagination = PageParams, db: Session = Depends(get_db)):
    conditions = []
    if category:
        conditions.append(AppLog.category == category)
    if level and level.upper() in LEVELS:
        conditions.append(AppLog.level.in_(LEVELS[LEVELS.index(level.upper()):]))
    if q and q.strip():
        conditions.append(AppLog.message.ilike(like_pattern(q), escape=LIKE_ESCAPE))
    if since:
        conditions.append(AppLog.created_at >= ensure_utc(since))
    if until:
        conditions.append(AppLog.created_at < ensure_utc(until))
    total = db.scalar(select(func.count(AppLog.id)).where(*conditions)) or 0
    rows = db.scalars(select(AppLog).where(*conditions).order_by(AppLog.id.desc()).limit(page.limit).offset(page.offset)).all()
    items = []
    for r in rows:
        try:
            details = json.loads(r.details_json or "{}")
        except json.JSONDecodeError:
            details = {}
        items.append(LogOut(id=r.id, created_at=r.created_at, level=r.level, category=r.category, logger=r.logger,
                            message=r.message, details=details))
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.delete("")
def clear_logs(db: Session = Depends(get_db)):
    result = db.execute(delete(AppLog))
    db.commit()
    return {"deleted": int(result.rowcount or 0)}
