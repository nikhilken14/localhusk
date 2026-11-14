from __future__ import annotations

from alembic import context
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

from assistant.core.config import get_settings
from assistant.db import models  # noqa: F401  (registers tables on Base.metadata)
from assistant.db.backup import backup_sqlite_database
from assistant.db.base import Base

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


def backup_before_migrating() -> None:
    target = backup_sqlite_database(settings.database_url, settings.backup_retention_days)
    if target:
        print(f"Database backed up to: {target}")


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"}, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)

    # Peek at the current revision on its OWN short-lived connection.  Doing this on the connection used for
    # the migration opens a transaction that Alembic does not own, so it never commits and every change
    # (including `alembic stamp`) is silently rolled back when the connection closes.
    with connectable.connect() as probe:
        current = MigrationContext.configure(probe).get_current_revision()
    head = ScriptDirectory.from_config(config).get_current_head()
    if current is not None and current != head:  # only back up when there is something to migrate
        backup_before_migrating()

    # engine.begin() guarantees a COMMIT on success (and ROLLBACK on error).
    with connectable.begin() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()