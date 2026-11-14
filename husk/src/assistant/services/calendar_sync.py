"""Pull events from connected Google / Microsoft accounts into local calendars (read-only mirror)."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from assistant.core.config import get_settings
from assistant.core.errors import APIError
from assistant.core.timeutil import utcnow
from assistant.db.models import Calendar, CalendarEvent, MailAccount
from assistant.services.mail.service import call_provider, has_calendar_scope, provider_for

log = logging.getLogger("assistant.calendar")


def sync_account_calendars(db: Session, account: MailAccount) -> dict:
    settings = get_settings()
    provider = provider_for(account.provider)
    now = utcnow()
    window_start = now - timedelta(days=settings.calendar_sync_past_days)
    window_end = now + timedelta(days=settings.calendar_sync_future_days)

    remote_calendars = call_provider(db, account, provider.list_calendars)
    local = {c.external_id: c for c in db.scalars(select(Calendar).where(Calendar.account_id == account.id))}
    remote_ids = {rc.external_id for rc in remote_calendars}
    for external_id, cal in list(local.items()):  # calendar deleted/unshared remotely
        if external_id not in remote_ids:
            db.delete(cal)
            del local[external_id]
    for rc in remote_calendars:
        cal = local.get(rc.external_id)
        if cal is None:
            cal = Calendar(provider=account.provider, account_id=account.id, external_id=rc.external_id, read_only=True)
            db.add(cal)
            local[rc.external_id] = cal
        cal.name, cal.color = rc.name[:200], rc.color[:20]
    db.flush()

    added = updated = removed = 0
    for rc in remote_calendars:
        cal = local[rc.external_id]
        if not cal.enabled:
            continue
        events = call_provider(db, account, lambda t, cid=rc.external_id: provider.list_events(t, cid, window_start, window_end))
        existing = {e.external_id: e for e in db.scalars(select(CalendarEvent).where(CalendarEvent.calendar_id == cal.id))}
        seen = set()
        for remote in events:
            seen.add(remote.external_id)
            row = existing.get(remote.external_id)
            if row is None:
                row = CalendarEvent(calendar_id=cal.id, external_id=remote.external_id, source=account.provider, title="", start_at=remote.start_at)
                db.add(row)
                added += 1
            else:
                updated += 1
            row.title, row.description, row.location = remote.title[:240], remote.description, remote.location[:300]
            row.start_at, row.end_at, row.all_day = remote.start_at, remote.end_at, remote.all_day
        stale = [e.id for ext, e in existing.items() if ext not in seen and window_start <= e.start_at <= window_end]
        if stale:
            db.execute(delete(CalendarEvent).where(CalendarEvent.id.in_(stale)).execution_options(synchronize_session=False))
            removed += len(stale)
        cal.last_synced_at = now
    db.commit()
    log.info("Calendar sync for %s: +%d ~%d -%d", account.email, added, updated, removed, extra={"category": "calendar"})
    return {"account_id": account.id, "provider": account.provider, "calendars": len(remote_calendars),
            "events_added": added, "events_updated": updated, "events_removed": removed}


def sync_calendars(db: Session, account_id: str | None = None) -> list[dict]:
    stmt = select(MailAccount).order_by(MailAccount.created_at)
    if account_id:
        stmt = stmt.where(MailAccount.id == account_id)
    accounts = db.scalars(stmt).all()
    if account_id and not accounts:
        raise APIError(404, "Account not found")
    results = []
    for account in accounts:
        if not has_calendar_scope(account):
            if account_id:
                raise APIError(409, "This account was connected without calendar access; reconnect it with calendar enabled",
                               "calendar_not_authorized")
            continue
        try:
            results.append(sync_account_calendars(db, account))
        except APIError as exc:
            if account_id:
                raise
            results.append({"account_id": account.id, "provider": account.provider, "error": exc.message, "code": exc.code})
    return results
