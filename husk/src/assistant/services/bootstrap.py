"""Startup tasks: schema migration and default data."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import inspect, text, update

from assistant.core.config import get_settings
from assistant.db.backup import backup_sqlite_database
from assistant.db.base import Base
from assistant.db.engine import engine
from assistant.db.models import Agent, CalendarEvent
from assistant.db.session import SessionLocal
from assistant.services.productivity import local_calendar

log = logging.getLogger("assistant.system")

# Migration chain and the tables each revision creates (used to recognise databases that were
# built without Alembic, e.g. by ``Base.metadata.create_all``).
REVISION_TABLES: list[tuple[str, set[str]]] = [
    ("0002_chat_providers", {"provider_configs", "conversations", "chat_messages"}),
    ("0003_productivity", {"notes", "tasks", "calendar_events"}),
    ("0004_agents_automation", {"mcp_servers", "agent_runs", "agent_approvals", "automation_jobs"}),
    ("0005_agent_run_events", {"agent_run_events"}),
    ("0006_backend_v1", {"agents", "mail_accounts", "mail_messages", "oauth_states", "calendars", "usage_records", "app_logs"}),
    ("0008_chat_attachments", {"chat_attachments"}),
]


class UntrackedDatabaseError(RuntimeError):
    pass


def choose_stamp_revision(tables: set[str], has_version_row: bool, columns_by_table: dict[str, set[str]] | None = None) -> str | None:
    """Which revision to ``alembic stamp`` for a database Alembic knows nothing about.

    Returns ``None`` when no stamping is needed (fresh database, or already tracked).  Raises
    ``UntrackedDatabaseError`` if the existing tables don't match any revision cleanly.
    """
    app_tables = tables - {"alembic_version"}
    if has_version_row or not app_tables:
        return None
    best: str | None = None
    seen: set[str] = set()
    for index, (revision, created) in enumerate(REVISION_TABLES):
        seen |= created
        later = set().union(*(t for _, t in REVISION_TABLES[index + 1:])) if index + 1 < len(REVISION_TABLES) else set()
        if seen <= app_tables and not (later & app_tables):
            best = revision
    if best is None:
        raise UntrackedDatabaseError(
            "The database contains tables that don't match any known schema version "
            f"({', '.join(sorted(app_tables))}). Back it up and delete it (or point DATABASE_URL at a new file) so a "
            "clean database can be created.")
    # Tables alone cannot distinguish 0006 from a database created directly from the
    # current ORM metadata: 0007 adds a column to an existing table. Inspect that column
    # before stamping so the next migration does not attempt to add it twice.
    if best == "0006_backend_v1" and "skip_if_running" in (columns_by_table or {}).get("automation_jobs", set()):
        best = "0007_automation_overlap_guard"
    if best == "0007_automation_overlap_guard" and "chat_attachments" in app_tables:
        best = "0008_chat_attachments"
    return best


def _current_version() -> str | None:
    """Read the stored Alembic revision on a fresh connection (None if the table/row is missing)."""
    if "alembic_version" not in set(inspect(engine).get_table_names()):
        return None
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def run_migrations() -> None:
    root = Path(__file__).resolve().parents[3]  # src/assistant/services -> project root
    ini = root / "alembic.ini"
    if not ini.exists():
        log.warning("alembic.ini not found (non-source install?); creating missing tables only. "
                    "Existing databases will NOT be upgraded.")
        Base.metadata.create_all(engine)
        return
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ini))
    cfg.set_main_option("script_location", str(root / "alembic"))

    settings = get_settings()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    columns_by_table = {table: {column["name"] for column in inspector.get_columns(table)} for table in tables}
    has_row = _current_version() is not None
    stamp = choose_stamp_revision(tables, has_row, columns_by_table)
    if stamp:
        backup = backup_sqlite_database(settings.database_url, settings.backup_retention_days)
        log.warning("Database has tables but no Alembic version (created outside migrations). Backed up to %s and "
                    "marking it as revision %s before upgrading.", backup, stamp)
        command.stamp(cfg, stamp)
        # Fail loudly if the stamp did not persist; otherwise `upgrade` would re-run old migrations
        # against tables that already exist ("table ... already exists").
        stored = _current_version()
        if stored != stamp:
            raise RuntimeError(f"Failed to stamp database as {stamp} (alembic_version holds {stored!r}). "
                               "Check that alembic/env.py commits its transaction.")
    command.upgrade(cfg, "head")


# Pre-built agents seeded on first run (matched by exact name). Users can edit or disable them.
PREBUILT_AGENTS: list[dict] = [
    {
        "name": "Mail Assistant",
        "description": "Reads, searches, and sends email from your connected Google or Microsoft accounts.",
        "system_prompt": (
            "You are Husk Mail Assistant. Help the user manage email using only the mail tools. "
            "Summarise threads clearly, never invent messages, and ask before sending. "
            "When listing mail, prefer the inbox unless the user asks otherwise. "
            "Always confirm recipients and subject before calling mail.send. "
            "When saving a summary or draft into notes, put the full body in content (not only the title) "
            "and use notes.update if you need to refine an existing note."
        ),
        "tools": ["mail.list", "mail.get", "mail.send", "mail.mark_read", "notes.create", "notes.update", "notes.list"],
    },
    {
        "name": "Task Manager",
        "description": "Creates, lists, and updates local tasks. Good for daily planning and status changes.",
        "system_prompt": (
            "You are Husk Task Manager. Manage the user's local tasks with tasks.list, tasks.create, and tasks.update. "
            "Keep titles short and actionable. Prefer status values: todo, in_progress, done. "
            "When the user says they finished something, mark it done. Confirm before bulk changes. "
            "If you write a plan or notes, put the full detail in note content and use notes.update to refine."
        ),
        "tools": ["tasks.list", "tasks.create", "tasks.update", "notes.create", "notes.update", "notes.list"],
    },
    {
        "name": "Notes Helper",
        "description": "Creates, updates, and finds local notes. Use for quick capture and retrieval.",
        "system_prompt": (
            "You are Husk Notes Helper. Capture and retrieve notes with notes.list, notes.get, notes.create, and notes.update. "
            "Use colour red for high importance, yellow for normal, green for low. "
            "Keep titles short; ALWAYS put the full detail, summary, or result in the content field. "
            "Prefer searching before creating duplicates. After create, use notes.update when you need to expand or correct content."
        ),
        "tools": ["notes.list", "notes.get", "notes.create", "notes.update"],
    },
    {
        "name": "Calendar Planner",
        "description": "Plans and schedules local calendar events; can also create related tasks and notes.",
        "system_prompt": (
            "You are Husk Calendar Planner. Work only with the local calendar (calendar.list, calendar.create) "
            "and tasks/notes when helpful. Use ISO-8601 datetimes with timezone when possible. "
            "For all-day events set all_day true and use a date-only start. "
            "Never invent events that were not requested. Propose a short plan, then create events after confirmation. "
            "If the user mentions deadlines, offer a matching task as well. "
            "When saving plans into notes, put the full body in content and use notes.update to refine."
        ),
        "tools": ["calendar.list", "calendar.create", "tasks.list", "tasks.create", "notes.create", "notes.update", "notes.list"],
    },
]


def _seed_prebuilt_agents(db) -> None:
    """Insert the four starter agents once if no agent with the same name exists."""
    import json
    from sqlalchemy import select
    existing = {name for name in db.scalars(select(Agent.name))}
    created = 0
    for spec in PREBUILT_AGENTS:
        if spec["name"] in existing:
            continue
        db.add(Agent(
            name=spec["name"],
            description=spec["description"],
            system_prompt=spec["system_prompt"],
            tools_json=json.dumps(spec["tools"]),
            status="active",
        ))
        created += 1
    if created:
        log.info("Seeded %s pre-built agent(s)", created)



def _seed_model_from_env(db) -> None:
    """If no LLM models exist yet, create one from LLM_* env / .env so CLI and UI share the same row."""
    import os
    from sqlalchemy import select
    from assistant.db.models import ProviderConfig
    from assistant.core.secrets import store_secret, SecretStoreError
    if db.scalar(select(ProviderConfig.id).limit(1)) is not None:
        return
    model = (os.environ.get("LLM_MODEL") or "").strip()
    if not model:
        return
    kind = (os.environ.get("LLM_PROVIDER") or "openai").strip().lower()
    if kind not in ("openai", "ollama", "anthropic", "google"):
        kind = "openai"
    base_url = (os.environ.get("LLM_ENDPOINT") or "").strip() or None
    name = (os.environ.get("LLM_NAME") or f"Default {model}").strip()[:120]
    p = ProviderConfig(name=name, kind=kind, base_url=base_url, model=model, is_default=True)
    api_key = (os.environ.get("LLM_API_KEY") or "").strip()
    if api_key:
        try:
            from uuid import uuid4
            from assistant.core.secrets import store_secret
            ref = f"provider:{uuid4()}"
            store_secret(ref, api_key)
            p.credential_ref = ref
        except Exception:
            log.warning("Could not store LLM_API_KEY in keyring during bootstrap", extra={"category": "llm"})
    db.add(p)
    log.info("Seeded default LLM model from environment: %s / %s", kind, model)


def bootstrap() -> None:
    if get_settings().auto_migrate:
        run_migrations()
    with SessionLocal() as db:
        cal = local_calendar(db)
        db.execute(update(CalendarEvent).where(CalendarEvent.calendar_id.is_(None)).values(calendar_id=cal.id))
        _seed_prebuilt_agents(db)
        _seed_model_from_env(db)
        db.commit()