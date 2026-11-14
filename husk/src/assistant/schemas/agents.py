from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator



class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    system_prompt: str = Field(default="", max_length=20000)
    provider_id: str | None = Field(default=None, description="Model connection; omit to use the workspace default")
    tools: list[str] = Field(default_factory=list, description="Tool ids from GET /agents/catalog")
    # Optional so PUT does not re-activate a paused agent when the client omits status.
    status: Literal["active", "paused"] | None = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("tools")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


class RunIn(BaseModel):
    # Allow empty input when attachments carry the goal context.
    input: str = Field(default="", max_length=10000, description="What the agent should do")
    plan: dict | None = Field(default=None, description="Optional pre-built plan {steps:[{tool,arguments}]}; skips LLM planning")
    attachment_ids: list[str] = Field(default_factory=list, max_length=8, description="Document ids from POST /agents/{id}/attachments")

    @field_validator("input")
    @classmethod
    def input_strip(cls, value: str) -> str:
        return (value or "").strip()


class ResolveIn(BaseModel):
    decision: Literal["approved", "rejected", "approve", "reject"]
    note: str = Field(default="", max_length=500)

    @property
    def normalized(self) -> str:
        return "approved" if self.decision.startswith("approve") else "rejected"
