"""Provider-neutral data types and pure helpers (no network, no database)."""
from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, parseaddr


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ReauthRequired(ProviderError):
    """The stored credentials no longer work; the person must reconnect the account."""


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str = ""


@dataclass
class RemoteMessage:
    external_id: str
    folder: str
    subject: str = ""
    sender_name: str = ""
    sender_email: str = ""
    to: list[dict] = field(default_factory=list)
    cc: list[dict] = field(default_factory=list)
    snippet: str = ""
    body_text: str = ""
    body_html: str = ""
    thread_id: str = ""
    is_read: bool = False
    has_attachments: bool = False
    received_at: datetime | None = None
    rfc_message_id: str = ""
    body_loaded: bool = False


@dataclass
class OutgoingMessage:
    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    html: bool = False


@dataclass
class RemoteCalendar:
    external_id: str
    name: str
    color: str = "#4f8cff"


@dataclass
class RemoteEvent:
    external_id: str
    title: str
    start_at: datetime
    end_at: datetime | None = None
    description: str = ""
    location: str = ""
    all_day: bool = False


# ---------------------------------------------------------------- PKCE / state
def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:100]  # RFC 7636: 43-128 chars


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------- parsing helpers
def parse_address(value: str) -> dict:
    name, email = parseaddr(value or "")
    return {"name": name, "email": email.lower()}


def parse_address_list(value: str) -> list[dict]:
    return [{"name": n, "email": e.lower()} for n, e in getaddresses([value or ""]) if e]


def parse_iso(value: str | None) -> datetime | None:
    """Parse ISO-8601 including Graph's 7-digit fractions and offset-less (UTC) values."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def parse_date_start(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def all_day_end(exclusive_end: datetime | None, start: datetime) -> datetime:
    """Providers give all-day events an exclusive end date; store the last second of the final day."""
    if exclusive_end is None or exclusive_end <= start:
        return start + timedelta(days=1) - timedelta(seconds=1)
    return exclusive_end - timedelta(seconds=1)


def strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def build_mime(sender: str, message: OutgoingMessage, *, in_reply_to: str = "", references: str = "") -> EmailMessage:
    """RFC 5322 message used for the Gmail API ``raw`` field."""
    mime = EmailMessage()
    mime["From"] = sender
    mime["To"] = ", ".join(message.to)
    if message.cc:
        mime["Cc"] = ", ".join(message.cc)
    if message.bcc:
        mime["Bcc"] = ", ".join(message.bcc)
    mime["Subject"] = message.subject
    if in_reply_to:
        mime["In-Reply-To"] = in_reply_to
        mime["References"] = (references + " " + in_reply_to).strip()
    if message.html:
        mime.set_content(strip_tags(message.body) or " ")
        mime.add_alternative(message.body, subtype="html")
    else:
        mime.set_content(message.body)
    return mime


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def b64url_decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def reply_subject(subject: str) -> str:
    return subject if re.match(r"(?i)^\s*re:", subject or "") else f"Re: {subject}".strip()


def addresses_for_reply(original_from: dict, reply_to: str, to: list[dict], cc: list[dict],
                        self_email: str, reply_all: bool) -> tuple[list[str], list[str]]:
    primary = parse_address(reply_to)["email"] if reply_to else original_from.get("email", "")
    to_list = [primary] if primary else []
    cc_list: list[str] = []
    if reply_all:
        seen = {self_email.lower(), *to_list}
        for entry in [*to, *cc]:
            email = entry.get("email", "")
            if email and email not in seen:
                seen.add(email)
                cc_list.append(email)
    return to_list, cc_list


__all__ = [n for n in dir() if not n.startswith("_")] + ["formataddr"]
