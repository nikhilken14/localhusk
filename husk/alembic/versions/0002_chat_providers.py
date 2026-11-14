"""Create provider and chat tables."""
from alembic import op
import sqlalchemy as sa
revision = "0002_chat_providers"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("provider_configs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(120), nullable=False), sa.Column("kind", sa.String(40), nullable=False), sa.Column("base_url", sa.String(500)), sa.Column("model", sa.String(200), nullable=False), sa.Column("credential_ref", sa.String(300)), sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="2048"), sa.Column("temperature", sa.Float(), nullable=False, server_default="0.7"), sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("conversations", sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(240), nullable=False, server_default="New chat"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("chat_messages", sa.Column("id", sa.String(36), primary_key=True), sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False), sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False), sa.Column("provider_id", sa.String(36), sa.ForeignKey("provider_configs.id", ondelete="SET NULL")), sa.Column("model", sa.String(200)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_chat_messages_conversation_created", "chat_messages", ["conversation_id", "created_at"])

def downgrade():
    op.drop_index("ix_chat_messages_conversation_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_table("conversations")
    op.drop_table("provider_configs")
