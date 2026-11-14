from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_updated_at", "updated_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(240), default="New chat", nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("provider_configs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_conversation_created", "conversation_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("provider_configs.id", ondelete="SET NULL"))
    model: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="complete")  # complete | partial | error
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ChatAttachment(Base):
    """Uploaded document for chat or agent context; extracted text is fed to the LLM."""
    __tablename__ = "chat_attachments"
    __table_args__ = (
        Index("ix_chat_attachments_conversation", "conversation_id", "created_at"),
        Index("ix_chat_attachments_agent", "agent_id", "created_at"),
        Index("ix_chat_attachments_run", "run_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)  # relative to attachments root
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extracted_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
