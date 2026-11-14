"""Application settings.

Values are read from the process environment, then ``./.env``, then
``~/.husk/.env`` (earlier sources win).  List-like values (CORS origins, allowed hosts)
accept either a comma separated string or a JSON array so ``.env`` files stay simple.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "1.0.0"
HUSK_HOME = Path(os.environ.get("HUSK_HOME", Path.home() / ".husk")).expanduser()


def _split_list(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value)
            return [str(v).strip() for v in parsed if str(v).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in value.split(",") if part.strip()]


class Settings(BaseSettings):
    app_name: str = "LocalHusk"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = 8000
    public_base_url: str = "http://127.0.0.1:8000"  # used to build the OAuth redirect URI
    frontend_url: str = "http://localhost:5173"

    database_url: str = f"sqlite:///{HUSK_HOME / 'data' / 'husk.db'}"
    auto_migrate: bool = True  # run `alembic upgrade head` on startup (source installs only)
    enable_workers: bool = True  # agent worker + automation scheduler

    log_level: str = "INFO"
    log_retention_days: int = 14
    max_log_rows: int = 50000

    # Stored as plain strings: comma separated or JSON array.
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    allowed_hosts: str = "127.0.0.1,localhost,[::1]"

    history_retention_days: int = 5  # default *view* window for /history
    history_auto_prune: bool = False  # permanently delete chats older than the window
    backup_retention_days: int = 30
    max_history_messages: int = 40  # messages sent to the LLM as context

    # Mail / calendar OAuth.  Leave blank to disable a provider.
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""  # optional for public (PKCE) clients
    microsoft_tenant: str = "common"
    mail_sync_limit: int = 50
    calendar_sync_past_days: int = 30
    calendar_sync_future_days: int = 180

    model_config = SettingsConfigDict(
        env_file=(str(HUSK_HOME / ".env"), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return _split_list(self.cors_origins)

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.lower() for h in _split_list(self.allowed_hosts)]

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}{self.api_v1_prefix}/mail/accounts/oauth/callback"

    def ensure_local_directories(self) -> None:
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix) and not self.database_url.endswith(":memory:"):
            path = Path(self.database_url[len(prefix):])
            if not path.is_absolute():
                path = Path.cwd() / path
            path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
