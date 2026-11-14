"""Deferred run retry metadata + agent-scoped attachments."""
from alembic import op
import sqlalchemy as sa

revision = "0009_deferred_retries_and_agent_attachments"
down_revision = "0008_chat_attachments"
branch_labels = None
depends_on = None


def upgrade():
    # Agent run retry / backoff fields
    op.add_column("agent_runs", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agent_runs", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))

    # Allow attachments to be owned by an agent (or a run) as well as a conversation
    with op.batch_alter_table("chat_attachments") as batch:
        batch.alter_column("conversation_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("agent_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("run_id", sa.String(36), nullable=True))
    op.create_index("ix_chat_attachments_agent", "chat_attachments", ["agent_id", "created_at"])
    op.create_index("ix_chat_attachments_run", "chat_attachments", ["run_id"])


def downgrade():
    op.drop_index("ix_chat_attachments_run", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_agent", table_name="chat_attachments")
    with op.batch_alter_table("chat_attachments") as batch:
        batch.drop_column("run_id")
        batch.drop_column("agent_id")
        batch.alter_column("conversation_id", existing_type=sa.String(36), nullable=False)
    op.drop_column("agent_runs", "next_retry_at")
    op.drop_column("agent_runs", "retry_count")
