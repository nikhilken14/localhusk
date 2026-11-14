from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from assistant.core.timeutil import utcnow
from assistant.db.base import Base
from assistant.db.types import UTCDateTime


def _uuid() -> str:
    return str(uuid4())


class MCPServer(Base):
    __tablename__ = "mcp_servers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    transport: Mapped[str] = mapped_column(String(20), nullable=False, default="http")
    command: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    args_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")  # unknown|connected|error|disabled|unsupported
    last_error: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    last_connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("provider_configs.id", ondelete="SET NULL"))
    tools_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active | paused
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


class AutomationJob(Base):
    __tablename__ = "automation_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    trigger_config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id", ondelete="SET NULL"))
    input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    skip_if_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_status_created", "status", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    agent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("automation_jobs.id", ondelete="SET NULL"), index=True)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")  # manual | api | schedule | event
    goal: Mapped[str] = mapped_column(Text, nullable=False)  # natural-language input
    plan_json: Mapped[str | None] = mapped_column(Text)  # validated plan once created
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    event_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Deferred-run retry policy (LLM offline / unreachable)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow)


class AgentApproval(Base):
    __tablename__ = "agent_approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_index: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(300), nullable=False)  # tool id
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")  # JSON {"arguments": {...}}
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|approved|rejected|executed
    resolution_note: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
