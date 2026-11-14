"""Add notes, tasks and local calendar events."""
from alembic import op
import sqlalchemy as sa
revision = "0003_productivity"
down_revision = "0002_chat_providers"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("notes",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("priority", sa.String(12), nullable=False),
        sa.Column("color", sa.String(12), nullable=False), sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_notes_priority_updated", "notes", ["priority", "updated_at"])
    op.create_table("tasks",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(12), nullable=False), sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("position", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_tasks_status_due", "tasks", ["status", "due_at"])
    op.create_table("calendar_events",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True)), sa.Column("location", sa.String(300), nullable=False),
        sa.Column("source", sa.String(20), nullable=False), sa.Column("external_id", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_calendar_events_start", "calendar_events", ["start_at"])

def downgrade():
    op.drop_index("ix_calendar_events_start", table_name="calendar_events"); op.drop_table("calendar_events")
    op.drop_index("ix_tasks_status_due", table_name="tasks"); op.drop_table("tasks")
    op.drop_index("ix_notes_priority_updated", table_name="notes"); op.drop_table("notes")
