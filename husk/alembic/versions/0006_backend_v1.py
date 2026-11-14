"""Backend v1: agents, mail/calendar accounts, usage, logs; richer chat/tasks/runs/MCP.

SQLite cannot ALTER constraints or add columns with non-constant defaults, so tables that gain
foreign keys or timestamp columns are rebuilt with ``recreate="always"`` (data is copied).
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0006_backend_v1"
down_revision = "0005_agent_run_events"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def _dt(name, nullable=True, default=None):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable, server_default=default)


def upgrade():
    bind = op.get_bind()

    # ---- new tables (parents first)
    op.create_table(
        "mail_accounts",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("email", sa.String(320), nullable=False), sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="connected"), sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("calendar_enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("credential_ref", sa.String(300)),
        _dt("last_synced_at"), sa.Column("last_error", sa.String(500), nullable=False, server_default=""),
        _dt("created_at", False, NOW), _dt("updated_at", False, NOW),
        sa.UniqueConstraint("provider", "email", name="uq_mail_accounts_provider_email"),
    )
    op.create_table(
        "mail_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(400), nullable=False), sa.Column("thread_id", sa.String(400), nullable=False, server_default=""),
        sa.Column("folder", sa.String(20), nullable=False, server_default="inbox"), sa.Column("subject", sa.String(1000), nullable=False, server_default=""),
        sa.Column("sender_name", sa.String(300), nullable=False, server_default=""), sa.Column("sender_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("to_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("cc_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("snippet", sa.String(600), nullable=False, server_default=""), sa.Column("body_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("body_html", sa.Text(), nullable=False, server_default=""), sa.Column("body_loaded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("has_attachments", sa.Boolean(), nullable=False, server_default=sa.false()),
        _dt("received_at", False, NOW), _dt("created_at", False, NOW),
        sa.UniqueConstraint("account_id", "external_id", name="uq_mail_messages_account_external"),
    )
    op.create_index("ix_mail_messages_account_folder_received", "mail_messages", ["account_id", "folder", "received_at"])
    op.create_table(
        "oauth_states",
        sa.Column("state", sa.String(100), primary_key=True), sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("code_verifier", sa.String(200), nullable=False), sa.Column("include_calendar", sa.Boolean(), nullable=False, server_default=sa.true()),
        _dt("created_at", False, NOW), _dt("expires_at", False),
    )
    op.create_table(
        "calendars",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider", sa.String(20), nullable=False, server_default="local"),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("mail_accounts.id", ondelete="CASCADE")), sa.Column("external_id", sa.String(400)),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("color", sa.String(20), nullable=False, server_default="#4f8cff"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        _dt("last_synced_at"), _dt("created_at", False, NOW),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""), sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider_id", sa.String(36), sa.ForeignKey("provider_configs.id", ondelete="SET NULL")),
        sa.Column("tools_json", sa.Text(), nullable=False, server_default="[]"), sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        _dt("created_at", False, NOW), _dt("updated_at", False, NOW),
    )
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("provider_id", sa.String(36)),
        sa.Column("provider_name", sa.String(120), nullable=False, server_default=""), sa.Column("provider_kind", sa.String(40), nullable=False, server_default=""),
        sa.Column("model", sa.String(200), nullable=False, server_default=""), sa.Column("source", sa.String(20), nullable=False, server_default="chat"),
        sa.Column("reference_id", sa.String(36)), sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"), sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        _dt("created_at", False, NOW),
    )
    op.create_index("ix_usage_records_created_at", "usage_records", ["created_at"])
    op.create_table(
        "app_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), _dt("created_at", False, NOW),
        sa.Column("level", sa.String(10), nullable=False), sa.Column("category", sa.String(30), nullable=False, server_default="system"),
        sa.Column("logger", sa.String(120), nullable=False, server_default=""), sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_app_logs_created_at", "app_logs", ["created_at"])
    op.create_index("ix_app_logs_category_level", "app_logs", ["category", "level"])

    # ---- existing tables
    with op.batch_alter_table("conversations", recreate="always") as b:
        b.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("provider_id", sa.String(36)))
        b.create_foreign_key("fk_conversations_provider_id", "provider_configs", ["provider_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_conversations_updated_at", ["updated_at"])
    with op.batch_alter_table("chat_messages") as b:
        b.add_column(sa.Column("status", sa.String(12), nullable=False, server_default="complete"))
        b.add_column(sa.Column("input_tokens", sa.Integer()))
        b.add_column(sa.Column("output_tokens", sa.Integer()))
    with op.batch_alter_table("provider_configs") as b:
        b.add_column(sa.Column("last_test_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("last_test_ok", sa.Boolean()))
        b.add_column(sa.Column("last_test_latency_ms", sa.Integer()))
        b.add_column(sa.Column("last_test_error", sa.String(400)))
    # tasks: title + description + priority  ->  a single `task` line
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("task", sa.String(800), nullable=False, server_default=""))
    op.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'done'")
    op.execute("UPDATE tasks SET task = SUBSTR(CASE WHEN description IS NULL OR description = '' THEN title "
               "ELSE title || ' - ' || description END, 1, 800)")
    with op.batch_alter_table("tasks", recreate="always") as b:
        b.drop_column("title")
        b.drop_column("description")
        b.drop_column("priority")
    # notes: colour (red/yellow/green) now carries the importance that `priority` used to
    with op.batch_alter_table("notes", recreate="always") as b:
        b.drop_index("ix_notes_priority_updated")
        b.drop_column("priority")
        b.create_index("ix_notes_color_updated", ["color", "updated_at"])
    with op.batch_alter_table("calendar_events", recreate="always") as b:
        b.add_column(sa.Column("calendar_id", sa.String(36)))
        b.add_column(sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.alter_column("external_id", existing_type=sa.String(300), type_=sa.String(400))
        b.create_foreign_key("fk_calendar_events_calendar_id", "calendars", ["calendar_id"], ["id"], ondelete="CASCADE")
        b.create_index("ix_calendar_events_calendar_external", ["calendar_id", "external_id"])
    with op.batch_alter_table("mcp_servers", recreate="always") as b:
        b.add_column(sa.Column("status", sa.String(20), nullable=False, server_default="unknown"))
        b.add_column(sa.Column("last_error", sa.String(500), nullable=False, server_default=""))
        b.add_column(sa.Column("last_connected_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("tools_json", sa.Text(), nullable=False, server_default="[]"))
        b.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW))
    op.execute("UPDATE mcp_servers SET updated_at = created_at")
    with op.batch_alter_table("automation_jobs", recreate="always") as b:
        b.add_column(sa.Column("agent_id", sa.String(36)))
        b.add_column(sa.Column("input", sa.Text(), nullable=False, server_default=""))
        b.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW))
        b.create_foreign_key("fk_automation_jobs_agent_id", "agents", ["agent_id"], ["id"], ondelete="SET NULL")
    op.execute("UPDATE automation_jobs SET updated_at = created_at")
    with op.batch_alter_table("agent_runs", recreate="always") as b:
        b.add_column(sa.Column("agent_id", sa.String(36)))
        b.add_column(sa.Column("job_id", sa.String(36)))
        b.add_column(sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"))
        b.add_column(sa.Column("plan_json", sa.Text()))
        b.add_column(sa.Column("event_seq", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("finished_at", sa.DateTime(timezone=True)))
        b.create_foreign_key("fk_agent_runs_agent_id", "agents", ["agent_id"], ["id"], ondelete="SET NULL")
        b.create_foreign_key("fk_agent_runs_job_id", "automation_jobs", ["job_id"], ["id"], ondelete="SET NULL")
        b.create_index("ix_agent_runs_agent_id", ["agent_id"])
        b.create_index("ix_agent_runs_job_id", ["job_id"])
        b.create_index("ix_agent_runs_status_created", ["status", "created_at"])
    with op.batch_alter_table("agent_approvals", recreate="always") as b:
        b.add_column(sa.Column("step_index", sa.Integer()))
        b.add_column(sa.Column("resolution_note", sa.String(500), nullable=False, server_default=""))
        b.alter_column("action", existing_type=sa.String(120), type_=sa.String(300))

    # ---- data migration: v0.9 stored the JSON plan in `goal`
    op.execute("UPDATE agent_runs SET started_at = created_at WHERE status <> 'queued'")
    op.execute("UPDATE agent_runs SET finished_at = updated_at WHERE status IN ('completed','failed','cancelled')")
    op.execute("UPDATE agent_runs SET event_seq = COALESCE((SELECT MAX(sequence) FROM agent_run_events e WHERE e.run_id = agent_runs.id), 0)")
    for run_id, goal in bind.execute(sa.text("SELECT id, goal FROM agent_runs")).fetchall():
        try:
            plan = json.loads(goal)
        except (TypeError, ValueError):
            continue
        if not isinstance(plan, dict):
            continue
        if "tool" in plan and "steps" not in plan:
            plan = {"steps": [{"tool": plan["tool"], "arguments": plan.get("arguments", {})}]}
        if isinstance(plan.get("steps"), list):
            names = ", ".join(str(s.get("tool", "?")) for s in plan["steps"] if isinstance(s, dict))
            bind.execute(sa.text("UPDATE agent_runs SET plan_json = :p, goal = :g WHERE id = :i"),
                         {"p": json.dumps(plan), "g": f"Imported plan: {names}"[:10000], "i": run_id})
    for approval_id, details in bind.execute(sa.text("SELECT id, details FROM agent_approvals")).fetchall():
        try:
            index = json.loads(details).get("_phase8_step_index")
        except (TypeError, ValueError, AttributeError):
            continue
        if isinstance(index, int):
            bind.execute(sa.text("UPDATE agent_approvals SET step_index = :s WHERE id = :i"), {"s": index, "i": approval_id})


def downgrade():
    with op.batch_alter_table("agent_approvals", recreate="always") as b:
        b.drop_column("step_index")
        b.drop_column("resolution_note")
    with op.batch_alter_table("agent_runs", recreate="always") as b:
        for index in ("ix_agent_runs_status_created", "ix_agent_runs_job_id", "ix_agent_runs_agent_id"):
            b.drop_index(index)
        for column in ("finished_at", "started_at", "output_tokens", "input_tokens", "event_seq", "plan_json", "trigger", "job_id", "agent_id"):
            b.drop_column(column)
    with op.batch_alter_table("automation_jobs", recreate="always") as b:
        for column in ("updated_at", "input", "agent_id"):
            b.drop_column(column)
    with op.batch_alter_table("mcp_servers", recreate="always") as b:
        for column in ("updated_at", "tools_json", "last_connected_at", "last_error", "status"):
            b.drop_column(column)
    with op.batch_alter_table("calendar_events", recreate="always") as b:
        b.drop_index("ix_calendar_events_calendar_external")
        b.drop_column("all_day")
        b.drop_column("calendar_id")
    with op.batch_alter_table("notes", recreate="always") as b:
        b.drop_index("ix_notes_color_updated")
        b.add_column(sa.Column("priority", sa.String(12), nullable=False, server_default="medium"))
        b.create_index("ix_notes_priority_updated", ["priority", "updated_at"])
    with op.batch_alter_table("tasks", recreate="always") as b:
        b.add_column(sa.Column("title", sa.String(240), nullable=False, server_default=""))
        b.add_column(sa.Column("description", sa.Text(), nullable=False, server_default=""))
        b.add_column(sa.Column("priority", sa.String(12), nullable=False, server_default="medium"))
    op.execute("UPDATE tasks SET title = SUBSTR(task, 1, 240)")
    with op.batch_alter_table("tasks", recreate="always") as b:
        b.drop_column("task")
        b.drop_column("completed_at")
    with op.batch_alter_table("provider_configs") as b:
        for column in ("last_test_error", "last_test_latency_ms", "last_test_ok", "last_test_at"):
            b.drop_column(column)
    with op.batch_alter_table("chat_messages") as b:
        for column in ("output_tokens", "input_tokens", "status"):
            b.drop_column(column)
    with op.batch_alter_table("conversations", recreate="always") as b:
        b.drop_index("ix_conversations_updated_at")
        for column in ("provider_id", "archived", "pinned"):
            b.drop_column(column)
    op.drop_index("ix_app_logs_category_level", table_name="app_logs")
    op.drop_index("ix_app_logs_created_at", table_name="app_logs")
    op.drop_table("app_logs")
    op.drop_index("ix_usage_records_created_at", table_name="usage_records")
    for table in ("usage_records", "agents", "calendars", "oauth_states"):
        op.drop_table(table)
    op.drop_index("ix_mail_messages_account_folder_received", table_name="mail_messages")
    op.drop_table("mail_messages")
    op.drop_table("mail_accounts")
