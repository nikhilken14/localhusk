"""Console logging plus a queued, non-blocking sink that stores ``assistant.*`` records in SQLite
so the UI can read them through ``GET /logs``."""
from __future__ import annotations

import json
import logging
import logging.handlers
import queue
from datetime import datetime, timezone

from assistant.core.redact import redact

CATEGORIES = ("api", "llm", "agent", "automation", "mcp", "mail", "calendar", "system")
_KEYWORDS = (
    ("agent", "agent"), ("automation", "automation"), ("scheduler", "automation"), ("mcp", "mcp"),
    ("mail", "mail"), ("calendar", "calendar"), ("llm", "llm"), ("chat", "llm"), ("provider", "llm"),
    ("api", "api"), ("request", "api"),
)


def category_for(logger_name: str, explicit: str | None = None) -> str:
    if explicit in CATEGORIES:
        return explicit  # type: ignore[return-value]
    lowered = logger_name.lower()
    for needle, category in _KEYWORDS:
        if needle in lowered:
            return category
    return "system"


class DBLogHandler(logging.Handler):
    """Writes records to ``app_logs``.  Never raises and never logs, to avoid feedback loops."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from assistant.db.models.log import AppLog
            from assistant.db.session import SessionLocal

            details: dict = {}
            if record.exc_info:
                details["traceback"] = redact(logging.Formatter().formatException(record.exc_info))[:6000]
            extra_details = getattr(record, "details", None)
            if isinstance(extra_details, dict):
                details.update(extra_details)
            with SessionLocal() as db:
                db.add(AppLog(
                    created_at=datetime.fromtimestamp(record.created, timezone.utc),
                    level=record.levelname,
                    category=category_for(record.name, getattr(record, "category", None)),
                    logger=record.name[:120],
                    message=redact(record.getMessage())[:4000],
                    details_json=json.dumps(details, default=str),
                ))
                db.commit()
        except Exception:  # noqa: BLE001
            pass


_listener: logging.handlers.QueueListener | None = None


def configure_logging(level: str = "INFO", *, store_in_db: bool = True) -> None:
    global _listener
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    app_logger = logging.getLogger("assistant")
    app_logger.setLevel(numeric)
    if store_in_db and _listener is None:
        log_queue: queue.Queue = queue.Queue(-1)
        app_logger.addHandler(logging.handlers.QueueHandler(log_queue))
        _listener = logging.handlers.QueueListener(log_queue, DBLogHandler(), respect_handler_level=True)
        _listener.start()


def shutdown_logging() -> None:
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
        for handler in list(logging.getLogger("assistant").handlers):
            if isinstance(handler, logging.handlers.QueueHandler):
                logging.getLogger("assistant").removeHandler(handler)
