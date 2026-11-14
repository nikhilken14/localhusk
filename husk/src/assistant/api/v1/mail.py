from __future__ import annotations

import html
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from assistant.api.dependencies import PageParams, Pagination, get_db
from assistant.core.config import get_settings
from assistant.core.errors import APIError
from assistant.core.textutil import LIKE_ESCAPE, like_pattern
from assistant.db.models import MailAccount, MailMessage
from assistant.schemas.common import Page
from assistant.schemas.mail import (
    AccountOut, MailSyncIn, MessageDetail, MessagePatch, MessageSummary, OAuthStartIn, Person, ReplyIn, SendIn,
)
from assistant.services.mail import service
from assistant.services.mail.common import OutgoingMessage

router = APIRouter(prefix="/mail", tags=["mail"])


def account_out(account: MailAccount) -> AccountOut:
    return AccountOut(id=account.id, provider=account.provider, email=account.email, display_name=account.display_name,
                      status=account.status, has_calendar=service.has_calendar_scope(account),
                      last_synced_at=account.last_synced_at, last_error=account.last_error, created_at=account.created_at)


def _people(raw: str) -> list[Person]:
    try:
        return [Person(**p) for p in json.loads(raw or "[]")]
    except (json.JSONDecodeError, TypeError):
        return []


def summary(m: MailMessage) -> dict:
    return dict(id=m.id, account_id=m.account_id, folder=m.folder, subject=m.subject,
                sender=Person(name=m.sender_name, email=m.sender_email), to=_people(m.to_json), snippet=m.snippet,
                is_read=m.is_read, has_attachments=m.has_attachments, received_at=m.received_at)


def _account(db: Session, account_id: str) -> MailAccount:
    account = db.get(MailAccount, account_id)
    if account is None:
        raise APIError(404, "Mail account not found")
    return account


def _message(db: Session, message_id: str) -> MailMessage:
    message = db.get(MailMessage, message_id)
    if message is None:
        raise APIError(404, "Message not found")
    return message


# ------------------------------------------------------------------ accounts
@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return [account_out(a) for a in db.scalars(select(MailAccount).order_by(MailAccount.created_at))]


@router.post("/accounts/oauth/start", summary="Begin Google/Microsoft authorization; open `authorization_url` in a browser")
def oauth_start(payload: OAuthStartIn, db: Session = Depends(get_db)):
    return service.start_oauth(db, payload.provider, payload.include_calendar)


def _callback_page(ok: bool, message: str, account_id: str | None = None) -> HTMLResponse:
    parsed = urlparse(get_settings().frontend_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else "*"
    data = json.dumps({"type": "husk-oauth", "ok": ok, "account_id": account_id, "message": message}).replace("<", "\\u003c")
    body = f"""<!doctype html><meta charset="utf-8"><title>Husk</title>
<body style="font-family:system-ui;margin:3rem;text-align:center">
<h2>{'Account connected' if ok else 'Connection failed'}</h2><p>{html.escape(message)}</p>
<p>You can close this window.</p>
<script>try{{window.opener&&window.opener.postMessage({data},{json.dumps(origin)});}}catch(e){{}}
if({str(ok).lower()})setTimeout(function(){{window.close()}},1200);</script></body>"""
    return HTMLResponse(body, status_code=200 if ok else 400)


@router.get("/accounts/oauth/callback", response_class=HTMLResponse, include_in_schema=True)
def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None,
                   error_description: str | None = None, db: Session = Depends(get_db)):
    """Provider redirect target.  Renders a small page that notifies the opener window."""
    if error or not code or not state:
        if state:  # abandon the pending request
            from assistant.db.models import OAuthState
            pending = db.get(OAuthState, state)
            if pending:
                db.delete(pending)
                db.commit()
        return _callback_page(False, error_description or error or "Authorization was cancelled")
    try:
        account = service.complete_oauth(db, state, code)
    except APIError as exc:
        return _callback_page(False, exc.message)
    return _callback_page(True, f"{account.email} is now connected", account.id)


@router.delete("/accounts/{account_id}", summary="Disconnect an account; revokes tokens where the provider supports it")
def delete_account(account_id: str, db: Session = Depends(get_db)):
    return {"deleted": True, **service.disconnect(db, _account(db, account_id))}


# ------------------------------------------------------------------ messages
@router.get("/messages", response_model=Page[MessageSummary])
def list_messages(account_id: str | None = None, folder: str = Query("inbox"), q: str | None = None,
                  unread: bool | None = None, has_attachments: bool | None = None,
                  page: Pagination = PageParams, db: Session = Depends(get_db)):
    if folder != "all" and folder not in service.FOLDERS:
        raise APIError(422, f"folder must be one of: all, {', '.join(service.FOLDERS)}")
    conditions = []
    if account_id:
        conditions.append(MailMessage.account_id == account_id)
    if folder != "all":
        conditions.append(MailMessage.folder == folder)
    if unread is not None:
        conditions.append(MailMessage.is_read.is_(not unread))
    if has_attachments is not None:
        conditions.append(MailMessage.has_attachments.is_(has_attachments))
    if q and q.strip():
        pattern = like_pattern(q)
        conditions.append(or_(*(col.ilike(pattern, escape=LIKE_ESCAPE) for col in
                                (MailMessage.subject, MailMessage.sender_name, MailMessage.sender_email, MailMessage.snippet))))
    total = db.scalar(select(func.count(MailMessage.id)).where(*conditions)) or 0
    rows = db.scalars(select(MailMessage).where(*conditions).order_by(MailMessage.received_at.desc())
                      .limit(page.limit).offset(page.offset)).all()
    return Page(items=[MessageSummary(**summary(m)) for m in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/messages/{message_id}", response_model=MessageDetail, summary="Full message (fetches the body on first open)")
def get_message(message_id: str, db: Session = Depends(get_db)):
    message = service.load_body(db, _message(db, message_id))
    return MessageDetail(**summary(message), thread_id=message.thread_id, cc=_people(message.cc_json),
                         body_text=message.body_text, body_html=message.body_html)


@router.patch("/messages/{message_id}", response_model=MessageSummary)
def patch_message(message_id: str, payload: MessagePatch, db: Session = Depends(get_db)):
    return MessageSummary(**summary(service.set_read(db, _message(db, message_id), payload.is_read)))


@router.post("/messages/{message_id}/send-reply", status_code=202)
def send_reply(message_id: str, payload: ReplyIn, db: Session = Depends(get_db)):
    service.send_reply(db, _message(db, message_id), payload.body, payload.html, payload.reply_all)
    return {"status": "sent"}


@router.post("/send", status_code=202)
def send_mail(payload: SendIn, db: Session = Depends(get_db)):
    account = _account(db, payload.account_id)
    service.send_new(db, account, OutgoingMessage(to=payload.to, cc=payload.cc, bcc=payload.bcc, subject=payload.subject,
                                                  body=payload.body, html=payload.html))
    return {"status": "sent"}


@router.post("/sync", summary="Synchronise inbox and sent mail")
def sync(payload: MailSyncIn | None = None, db: Session = Depends(get_db)):
    account_id = payload.account_id if payload else None
    accounts = [_account(db, account_id)] if account_id else list(db.scalars(select(MailAccount).order_by(MailAccount.created_at)))
    results = []
    for account in accounts:
        try:
            results.append(service.sync_mail(db, account))
        except APIError as exc:
            if account_id:
                raise
            results.append({"account_id": account.id, "provider": account.provider, "error": exc.message, "code": exc.code})
    return {"synced": results}
