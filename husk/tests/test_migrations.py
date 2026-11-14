"""Run the real Alembic migrations against throw-away databases."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alembic(db_path: Path, target: str):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "PYTHONPATH": str(ROOT / "src")}
    return subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=ROOT, env=env, capture_output=True, text=True)


def test_fresh_database_matches_models(tmp_path):
    db_path = tmp_path / "fresh.db"
    result = _alembic(db_path, "head")
    assert result.returncode == 0, result.stderr
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine
    from assistant.db import models  # noqa: F401
    from assistant.db.base import Base
    with create_engine(f"sqlite:///{db_path.as_posix()}").connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"migrations and models disagree: {diff}"


def test_upgrade_from_v09_preserves_and_converts_data(tmp_path):
    db_path = tmp_path / "legacy.db"
    assert _alembic(db_path, "0005_agent_run_events").returncode == 0
    plan = {"steps": [{"tool": "tasks.create", "arguments": {"title": "x"}}]}
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO agent_runs (id, goal, status, result, error, created_at, updated_at) VALUES "
                "('r1', ?, 'completed', '', '', '2026-10-20 10:00:00', '2026-10-20 10:01:00')", (json.dumps(plan),))
    con.execute("INSERT INTO agent_runs (id, goal, status, result, error, created_at, updated_at) VALUES "
                "('r2', 'plain text goal', 'queued', '', '', '2026-10-20 10:00:00', '2026-10-20 10:00:00')")
    con.execute("INSERT INTO agent_approvals (id, run_id, action, details, status, created_at) VALUES "
                "('a1', 'r1', 'tasks.create', ?, 'executed', '2026-10-20 10:00:30')", (json.dumps({"arguments": {"title": "x"}, "_phase8_step_index": 0}),))
    con.execute("INSERT INTO agent_run_events (id, run_id, sequence, event_type, message, details_json, created_at) VALUES "
                "('e1', 'r1', 3, 'run.completed', 'done', '{}', '2026-10-20 10:01:00')")
    con.execute("INSERT INTO tasks (id, title, description, status, priority, position, created_at, updated_at) VALUES "
                "('t1', 'Write report', '', 'done', 'medium', 0, '2026-10-20 10:00:00', '2026-10-20 11:00:00')")
    con.execute("INSERT INTO tasks (id, title, description, status, priority, position, created_at, updated_at) VALUES "
                "('t2', 'Call Sam', 'about the invoice', 'todo', 'high', 1, '2026-10-20 10:00:00', '2026-10-20 10:00:00')")
    con.execute("INSERT INTO notes (id, title, content, priority, color, pinned, created_at, updated_at) VALUES "
                "('n1', 'Idea', 'text', 'high', 'red', 0, '2026-10-20 10:00:00', '2026-10-20 10:00:00')")
    con.commit(); con.close()
    result = _alembic(db_path, "head")
    assert result.returncode == 0, result.stderr
    con = sqlite3.connect(db_path)
    plan_json, goal, event_seq, started, finished = con.execute("SELECT plan_json, goal, event_seq, started_at, finished_at FROM agent_runs WHERE id='r1'").fetchone()
    assert json.loads(plan_json) == plan and goal.startswith("Imported plan") and event_seq == 3 and started and finished
    assert con.execute("SELECT plan_json, goal, started_at FROM agent_runs WHERE id='r2'").fetchone() == (None, "plain text goal", None)
    assert con.execute("SELECT step_index FROM agent_approvals WHERE id='a1'").fetchone() == (0,)
    assert con.execute("SELECT completed_at FROM tasks WHERE id='t1'").fetchone()[0] == "2026-10-20 11:00:00"
    assert con.execute("SELECT task FROM tasks WHERE id='t1'").fetchone() == ("Write report",)
    assert con.execute("SELECT task FROM tasks WHERE id='t2'").fetchone() == ("Call Sam - about the invoice",)
    assert [c[1] for c in con.execute("PRAGMA table_info(tasks)")].count("title") == 0
    assert con.execute("SELECT title, color FROM notes WHERE id='n1'").fetchone() == ("Idea", "red")
    assert "priority" not in [c[1] for c in con.execute("PRAGMA table_info(notes)")]
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()


def test_database_created_outside_alembic_is_adopted_not_crashed(tmp_path):
    """Regression: a DB built by Base.metadata.create_all (no alembic_version) used to crash startup with
    'table provider_configs already exists'."""
    db_path = tmp_path / "untracked.db"
    assert _alembic(db_path, "0005_agent_run_events").returncode == 0
    con = sqlite3.connect(db_path)
    con.execute("DROP TABLE alembic_version"); con.commit(); con.close()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "PYTHONPATH": str(ROOT / "src")}
    code = "from assistant.services.bootstrap import run_migrations; run_migrations()"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone() == ("0007_automation_overlap_guard",)
    con.close()
    assert list((tmp_path / "backups").glob("husk_backup_*.db")), "the untracked database must be backed up before stamping"


def test_untracked_current_orm_schema_is_stamped_at_latest_revision(tmp_path):
    """A DB created from current ORM metadata already has the 0007 column and must not re-add it."""
    db_path = tmp_path / "current-orm.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "PYTHONPATH": str(ROOT / "src")}
    code = "from assistant.db.base import Base; from assistant.db.engine import engine; Base.metadata.create_all(engine)"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    env["AUTO_MIGRATE"] = "true"
    code = "from assistant.services.bootstrap import run_migrations; run_migrations()"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone() == ("0007_automation_overlap_guard",)
    assert [row[1] for row in con.execute("PRAGMA table_info(automation_jobs)")].count("skip_if_running") == 1
    con.close()
