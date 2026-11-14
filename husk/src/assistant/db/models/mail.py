from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


class MailAccount(Base):
    """A connected Google / Microsoft account.  The refresh token is in the OS keyring."""

    __tablename__ = "mail_accounts"
    __table_args__ = (UniqueConstraint("provider", "email", name="uq_mail_accounts_provider_email"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # google | microsoft
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="connected")  # connected | needs_reauth | error
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    calendar_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credential_ref: Mapped[str | None] = mapped_column(String(300))
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


class MailMessage(Base):
    __tablename__ = "mail_messages"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id", name="uq_mail_messages_account_external"),
        Index("ix_mail_messages_account_folder_received", "account_id", "folder", "received_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(400), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    folder: Mapped[str] = mapped_column(String(20), nullable=False, default="inbox")
    subject: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    sender_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    to_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    cc_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    snippet: Mapped[str] = mapped_column(String(600), nullable=False, default="")
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_loaded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class OAuthState(Base):
    """Short-lived, single-use record that ties an OAuth callback to the request that began it."""

    __tablename__ = "oauth_states"
    state: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(200), nullable=False)
    include_calendar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
