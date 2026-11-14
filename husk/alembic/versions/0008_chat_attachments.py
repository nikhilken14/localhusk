"""Chat file attachments for LLM context."""
from alembic import op
import sqlalchemy as sa

revision = "0008_chat_attachments"
down_revision = "0007_automation_overlap_guard"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("extracted_chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_attachments_conversation", "chat_attachments", ["conversation_id", "created_at"])


def downgrade():
    op.drop_index("ix_chat_attachments_conversation", table_name="chat_attachments")
    op.drop_table("chat_attachments")
