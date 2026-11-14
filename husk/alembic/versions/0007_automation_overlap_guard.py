"""Persist automation overlap policy."""
from alembic import op
import sqlalchemy as sa

revision = "0007_automation_overlap_guard"
down_revision = "0006_backend_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("automation_jobs", sa.Column("skip_if_running", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column("automation_jobs", "skip_if_running")
