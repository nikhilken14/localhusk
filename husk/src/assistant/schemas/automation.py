from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class JobIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    # Optional so clients that omit description do not wipe an existing value on PUT.
    description: str | None = None
    trigger_type: Literal["manual", "interval", "cron", "event"] = "manual"
    trigger_config: dict = Field(default_factory=dict)
    agent_id: str | None = None
    input: str = Field(default="", max_length=10000, description="Prompt for each run; falls back to description, then name")
    enabled: bool = False
    skip_if_running: bool = True

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class MCPIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    transport: Literal["http", "sse", "stdio"] = "http"
    command: str = Field(default="", max_length=500)
    args: list[str] = Field(default_factory=list)
    url: str = Field(default="", max_length=1000)
    enabled: bool = True
    require_approval: bool = True

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if v:
            parsed = urlparse(v)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("MCP URL must be a valid HTTP(S) URL without embedded credentials")
            loopback = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
            if parsed.scheme != "https" and not loopback:
                raise ValueError("MCP URL must use HTTPS or loopback HTTP")
        return v
