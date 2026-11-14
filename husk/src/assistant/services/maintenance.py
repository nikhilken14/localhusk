"""Periodic housekeeping: log retention, expired OAuth states, optional history pruning."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from assistant.core.config import get_settings
from assistant.core.timeutil import utcnow
from assistant.db.models import AppLog, Conversation, OAuthState

log = logging.getLogger("assistant.system")


def prune_history(db: Session, days: int) -> int:
    cutoff = utcnow() - timedelta(days=days)
    deleted = db.execute(delete(Conversation).where(Conversation.updated_at < cutoff, Conversation.pinned.is_(False)).execution_options(synchronize_session=False))
    db.commit()
    return int(deleted.rowcount or 0)


def run_maintenance(db: Session) -> None:
    settings = get_settings()
    db.execute(delete(AppLog).where(AppLog.created_at < utcnow() - timedelta(days=settings.log_retention_days)))
    total = db.scalar(select(func.count(AppLog.id))) or 0
    if total > settings.max_log_rows:
        cutoff_id = db.scalar(select(AppLog.id).order_by(AppLog.id.desc()).offset(settings.max_log_rows).limit(1))
        if cutoff_id is not None:
            db.execute(delete(AppLog).where(AppLog.id <= cutoff_id))
    db.execute(delete(OAuthState).where(OAuthState.expires_at < utcnow()))
    db.commit()
    if settings.history_auto_prune:
        removed = prune_history(db, settings.history_retention_days)
        if removed:
            log.info("Pruned %d conversations older than %d days", removed, settings.history_retention_days)
