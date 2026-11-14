from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from assistant.core.config import get_settings


def build_engine(url: str | None = None):
    settings = get_settings()
    url = url or settings.database_url
    kwargs: dict = {"pool_pre_ping": True}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        settings.ensure_local_directories()
        kwargs["connect_args"] = {"check_same_thread": False}
        if url.endswith(":memory:") or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")  # needed for ON DELETE CASCADE / SET NULL
            cursor.execute("PRAGMA journal_mode=WAL")  # readers don't block the worker thread
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine


engine = build_engine()
