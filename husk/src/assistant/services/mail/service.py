"""Mail accounts: OAuth, token handling, sync, send/reply.  All functions are blocking (HTTP);
call them from sync routes (run in FastAPI's threadpool) or via ``asyncio.to_thread``."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from assistant.core.config import get_settings
from assistant.core.errors import APIError
from assistant.core.redact import redact
from assistant.core.secrets import SecretStoreError, delete_secret, get_secret, store_secret
from assistant.core.timeutil import utcnow
from assistant.db.models import MailAccount, MailMessage, OAuthState
from assistant.services.automation import fire_event
from assistant.services.mail.common import (
    OutgoingMessage, ProviderError, ReauthRequired, RemoteMessage, TokenSet, code_challenge, new_code_verifier, new_state,
)
from assistant.services.mail.providers import CALENDAR_SCOPE_GOOGLE, CALENDAR_SCOPE_MICROSOFT, get_provider

log = logging.getLogger("assistant.mail")

FOLDERS = ("inbox", "sent", "drafts", "trash", "spam")
SYNC_FOLDERS = ("inbox", "sent")
_token_cache: dict[str, tuple[str, datetime]] = {}
_cache_lock = threading.Lock()


def provider_for(name: str):
    provider = get_provider(name)
    if provider is None:
        raise APIError(422, "provider must be 'google' or 'microsoft'")
    return provider


def has_calendar_scope(account: MailAccount) -> bool:
    return account.calendar_enabled and (CALENDAR_SCOPE_GOOGLE in account.scopes or CALENDAR_SCOPE_MICROSOFT in account.scopes)


# ------------------------------------------------------------------ OAuth
def start_oauth(db: Session, provider_name: str, include_calendar: bool) -> dict:
    provider = provider_for(provider_name)
    if not provider.configured():
        raise APIError(400, f"{provider_name.title()} sign-in is not configured. {provider.setup_hint()}", "oauth_not_configured")
    state, verifier = new_state(), new_code_verifier()
    db.add(OAuthState(state=state, provider=provider_name, code_verifier=verifier, include_calendar=include_calendar,
                      expires_at=utcnow() + timedelta(minutes=10)))
    db.commit()
    url = provider.authorization_url(get_settings().oauth_redirect_uri, state, code_challenge(verifier), include_calendar)
    return {"provider": provider_name, "authorization_url": url, "state": state,
            "redirect_uri": get_settings().oauth_redirect_uri, "expires_in": 600}


def complete_oauth(db: Session, state: str, code: str) -> MailAccount:
    """Exchange the authorization code for tokens and create/update the account."""
    row = db.get(OAuthState, state)
    if row is None or row.expires_at < utcnow():
        if row is not None:
            db.delete(row)
            db.commit()
        raise APIError(400, "Authorization request expired or unknown; start again", "oauth_state_invalid")
    provider = provider_for(row.provider)
    db.delete(row)  # single use
    db.commit()
    try:
        tokens = provider.exchange_code(code, row.code_verifier, get_settings().oauth_redirect_uri)
        email, name = provider.profile(tokens.access_token)
    except ProviderError as exc:
        raise APIError(502, f"Could not complete sign-in: {redact(str(exc))}", "oauth_failed") from exc
    if not tokens.refresh_token:
        raise APIError(502, "The provider did not return a refresh token; remove the app's access in your "
                            "account settings and connect again", "oauth_no_refresh_token")
    account = db.scalar(select(MailAccount).where(MailAccount.provider == row.provider, MailAccount.email == email))
    if account is None:
        account = MailAccount(provider=row.provider, email=email)
        db.add(account)
    ref = account.credential_ref or f"mail:{uuid4()}"
    try:
        store_secret(ref, tokens.refresh_token)
    except SecretStoreError as exc:
        raise APIError(503, str(exc), "secret_store_unavailable") from exc
    account.credential_ref = ref
    account.display_name = name or account.display_name
    account.scopes = tokens.scope or " ".join(provider.scopes(row.include_calendar))
    account.calendar_enabled = row.include_calendar
    account.status, account.last_error = "connected", ""
    db.commit()
    _remember_token(account.id, tokens)
    log.info("Connected %s account %s", row.provider, email, extra={"category": "mail"})
    return account


def _remember_token(account_id: str, tokens: TokenSet) -> None:
    with _cache_lock:
        _token_cache[account_id] = (tokens.access_token, utcnow() + timedelta(seconds=max(60, tokens.expires_in - 60)))


def _mark(db: Session, account: MailAccount, status: str, error: str) -> None:
    account.status, account.last_error = status, redact(error)[:500]
    db.commit()


def access_token(db: Session, account: MailAccount, *, force_refresh: bool = False) -> str:
    if not force_refresh:
        with _cache_lock:
            cached = _token_cache.get(account.id)
        if cached and cached[1] > utcnow():
            return cached[0]
    provider = provider_for(account.provider)
    try:
        refresh_token = get_secret(account.credential_ref)
    except SecretStoreError as exc:
        raise APIError(503, str(exc), "secret_store_unavailable") from exc
    if not refresh_token:
        _mark(db, account, "needs_reauth", "Stored credentials are missing")
        raise APIError(409, "Account credentials are missing; reconnect the account", "reauth_required")
    try:
        tokens = provider.refresh(refresh_token)
    except ReauthRequired as exc:
        _mark(db, account, "needs_reauth", str(exc))
        raise APIError(409, "The account needs to be reconnected", "reauth_required") from exc
    except ProviderError as exc:
        raise APIError(502, redact(str(exc)), "provider_error") from exc
    if tokens.refresh_token and tokens.refresh_token != refresh_token:  # Microsoft rotates refresh tokens
        store_secret(account.credential_ref, tokens.refresh_token)
    _remember_token(account.id, tokens)
    return tokens.access_token


def call_provider(db: Session, account: MailAccount, fn):
    """Run ``fn(token)``; refresh and retry once on 401; translate failures into API errors."""
    token = access_token(db, account)
    try:
        return fn(token)
    except ReauthRequired:
        token = access_token(db, account, force_refresh=True)
        try:
            return fn(token)
        except ReauthRequired as exc:
            _mark(db, account, "needs_reauth", str(exc))
            raise APIError(409, "The account needs to be reconnected", "reauth_required") from exc
        except ProviderError as exc:
            raise APIError(502, redact(str(exc)), "provider_error") from exc
    except ProviderError as exc:
        log.warning("Provider error for %s: %s", account.email, exc, extra={"category": "mail"})
        raise APIError(502, redact(str(exc)), "provider_error") from exc


def disconnect(db: Session, account: MailAccount) -> dict:
    revoked = False
    provider = get_provider(account.provider)
    try:
        refresh_token = get_secret(account.credential_ref)
        if provider and refresh_token:
            revoked = provider.revoke(refresh_token)
        delete_secret(account.credential_ref)
    except SecretStoreError as exc:
        raise APIError(503, str(exc), "secret_store_unavailable") from exc
    with _cache_lock:
        _token_cache.pop(account.id, None)
    db.delete(account)  # messages, calendars and calendar events cascade at the database level
    db.commit()
    log.info("Disconnected %s account %s (revoked=%s)", account.provider, account.email, revoked, extra={"category": "mail"})
    return {"revoked": revoked}


# ------------------------------------------------------------------ sync
def _apply_remote(row: MailMessage, remote: RemoteMessage) -> None:
    row.thread_id, row.folder, row.subject = remote.thread_id, remote.folder, remote.subject[:1000]
    row.sender_name, row.sender_email = remote.sender_name[:300], remote.sender_email[:320]
    row.to_json, row.cc_json = json.dumps(remote.to), json.dumps(remote.cc)
    row.snippet, row.is_read, row.has_attachments = remote.snippet[:600], remote.is_read, remote.has_attachments
    if remote.received_at:
        row.received_at = remote.received_at
    if remote.body_loaded:
        row.body_text, row.body_html, row.body_loaded = remote.body_text, remote.body_html, True


def sync_mail(db: Session, account: MailAccount, folders=SYNC_FOLDERS) -> dict:
    provider = provider_for(account.provider)
    limit = get_settings().mail_sync_limit
    first_sync = account.last_synced_at is None
    added = updated = 0
    for folder in folders:
        remote_list = call_provider(db, account, lambda t, f=folder: provider.list_messages(t, f, limit))
        ids = [r.external_id for r in remote_list]
        existing = {m.external_id: m for m in db.scalars(select(MailMessage).where(
            MailMessage.account_id == account.id, MailMessage.external_id.in_(ids)))} if ids else {}
        for remote in remote_list:
            row = existing.get(remote.external_id)
            if row is None:
                row = MailMessage(account_id=account.id, external_id=remote.external_id)
                _apply_remote(row, remote)
                db.add(row)
                db.flush()
                added += 1
                if folder == "inbox" and not first_sync and not remote.is_read:
                    fire_event(db, "mail.message_received", {"id": row.id, "account_id": account.id,
                                                             "subject": row.subject, "sender_email": row.sender_email, "folder": folder})
            else:
                changed = row.is_read != remote.is_read or row.folder != remote.folder
                _apply_remote(row, remote)
                updated += int(changed)
    account.last_synced_at, account.status, account.last_error = utcnow(), "connected", ""
    db.commit()
    log.info("Mail sync for %s: %d new, %d updated", account.email, added, updated, extra={"category": "mail"})
    return {"account_id": account.id, "provider": account.provider, "messages_added": added, "messages_updated": updated}


def load_body(db: Session, message: MailMessage) -> MailMessage:
    if message.body_loaded:
        return message
    account = db.get(MailAccount, message.account_id)
    provider = provider_for(account.provider)
    remote = call_provider(db, account, lambda t: provider.get_message(t, message.external_id, message.folder))
    message.body_text, message.body_html, message.body_loaded = remote.body_text, remote.body_html, True
    message.has_attachments = remote.has_attachments or message.has_attachments
    db.commit()
    return message


def set_read(db: Session, message: MailMessage, is_read: bool) -> MailMessage:
    if message.is_read != is_read:
        account = db.get(MailAccount, message.account_id)
        provider = provider_for(account.provider)
        call_provider(db, account, lambda t: provider.set_read(t, message.external_id, is_read))
        message.is_read = is_read
        db.commit()
    return message


def send_new(db: Session, account: MailAccount, message: OutgoingMessage) -> None:
    provider = provider_for(account.provider)
    call_provider(db, account, lambda t: provider.send(t, account.email, message))
    log.info("Sent email from %s to %d recipient(s)", account.email, len(message.to) + len(message.cc) + len(message.bcc),
             extra={"category": "mail"})


def send_reply(db: Session, message: MailMessage, body: str, html: bool, reply_all: bool) -> None:
    account = db.get(MailAccount, message.account_id)
    provider = provider_for(account.provider)
    call_provider(db, account, lambda t: provider.reply(t, account.email, message.external_id, body, html, reply_all))
    log.info("Sent reply from %s", account.email, extra={"category": "mail"})
