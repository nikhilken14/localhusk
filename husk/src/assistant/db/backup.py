"""Consistent, WAL-safe SQLite backups (uses SQLite's online backup API)."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path


def sqlite_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url.endswith(":memory:"):
        return None
    path = Path(database_url[len(prefix):])
    return path if path.is_absolute() else Path.cwd() / path


def backup_sqlite_database(database_url: str, retention_days: int) -> Path | None:
    """Copy the database to ``backups/husk_backup_<timestamp>.db`` next to it and prune old copies."""
    db_path = sqlite_path(database_url)
    if db_path is None or not db_path.exists():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"husk_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    source, dest = sqlite3.connect(db_path), sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    cutoff = time.time() - retention_days * 86400
    for old in backup_dir.glob("husk_backup_*.db"):
        if old.is_file() and old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    return target
