from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistant.core.errors import APIError
from assistant.core.textutil import preview
from assistant.core.timeutil import utcnow
from assistant.db.models import ChatMessage, Conversation
from assistant.providers.base import ChatMessageInput
from assistant.services.automation import fire_event


def get_conversation(db: Session, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise APIError(404, "Conversation not found")
    return conversation


def create_conversation(db: Session, title: str = "New chat", provider_id: str | None = None) -> Conversation:
    conversation = Conversation(title=title, provider_id=provider_id)
    db.add(conversation)
    db.flush()
    fire_event(db, "conversation.created", {"id": conversation.id, "title": conversation.title})
    db.commit()
    return conversation


def save_message(db: Session, conversation: Conversation, role: str, content: str, *, provider_id: str | None = None,
                 model: str | None = None, status: str = "complete", input_tokens: int | None = None,
                 output_tokens: int | None = None) -> ChatMessage:
    message = ChatMessage(conversation_id=conversation.id, role=role, content=content, provider_id=provider_id, model=model,
                          status=status, input_tokens=input_tokens, output_tokens=output_tokens)
    db.add(message)
    conversation.updated_at = utcnow()
    if role == "user" and conversation.title == "New chat":
        conversation.title = preview(content, 60) or "New chat"  # auto-title from the first message
    db.commit()
    db.refresh(message)
    return message


def build_history(db: Session, conversation_id: str, limit: int) -> list[ChatMessageInput]:
    """The most recent ``limit`` messages, oldest first (assistant errors/partials excluded)."""
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation_id, ChatMessage.status != "error")
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)
    ).all()
    messages = [m for m in reversed(rows) if m.status == "complete"]
    # Provider APIs require a user message to start a conversation; a sliced history
    # can begin with an assistant turn once the conversation gets long.
    while messages and messages[0].role != "user":
        messages.pop(0)
    return [ChatMessageInput(m.role, m.content) for m in messages]


def message_counts(db: Session, conversation_ids: list[str]) -> dict[str, int]:
    if not conversation_ids:
        return {}
    rows = db.execute(select(ChatMessage.conversation_id, func.count(ChatMessage.id))
                      .where(ChatMessage.conversation_id.in_(conversation_ids)).group_by(ChatMessage.conversation_id)).all()
    return {cid: count for cid, count in rows}


def window_start(days: int):
    return utcnow() - timedelta(days=days)
