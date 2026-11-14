from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from assistant.schemas.types import EmailAddress


class OAuthStartIn(BaseModel):
    provider: Literal["google", "microsoft"]
    include_calendar: bool = True


class AccountOut(BaseModel):
    id: str
    provider: str
    email: str
    display_name: str
    status: str
    has_calendar: bool
    last_synced_at: datetime | None
    last_error: str
    created_at: datetime


class Person(BaseModel):
    name: str = ""
    email: str = ""


class MessageSummary(BaseModel):
    id: str
    account_id: str
    folder: str
    subject: str
    sender: Person
    to: list[Person]
    snippet: str
    is_read: bool
    has_attachments: bool
    received_at: datetime


class MessageDetail(MessageSummary):
    thread_id: str
    cc: list[Person]
    body_text: str
    body_html: str = Field(description="Untrusted HTML from the sender - sanitise before rendering")


class MessagePatch(BaseModel):
    is_read: bool


class SendIn(BaseModel):
    account_id: str
    to: list[EmailAddress] = Field(min_length=1, max_length=50)
    cc: list[EmailAddress] = Field(default_factory=list, max_length=50)
    bcc: list[EmailAddress] = Field(default_factory=list, max_length=50)
    subject: str = Field(default="", max_length=998)
    body: str = Field(min_length=1, max_length=500_000)
    html: bool = False

    @field_validator("subject")
    @classmethod
    def reject_header_newlines(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("subject must not contain line breaks")
        return value


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=500_000)
    html: bool = False
    reply_all: bool = False


class MailSyncIn(BaseModel):
    account_id: str | None = None
