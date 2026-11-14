from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from assistant.schemas.common import PatchModel


class ConversationCreate(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=240)
    provider_id: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class ConversationUpdate(PatchModel):
    non_nullable: ClassVar[frozenset[str]] = frozenset({"title", "pinned", "archived"})
    title: str | None = Field(default=None, min_length=1, max_length=240)
    pinned: bool | None = None
    archived: bool | None = None
    provider_id: str | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("title must not be blank")
        return value


class MessageCreate(BaseModel):
    # Allow empty content when attachments are provided (validated in the route).
    content: str = Field(default="", max_length=100000)
    provider_id: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=128000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: str
    role: str
    content: str
    provider_id: str | None
    model: str | None
    status: str
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class ConversationRead(BaseModel):
    id: str
    title: str
    pinned: bool
    archived: bool
    provider_id: str | None
    message_count: int
    preview: str
    created_at: datetime
    updated_at: datetime


class SendResult(BaseModel):
    user_message: MessageRead
    assistant_message: MessageRead
    usage: dict
