"""Persist agent run events for frontend progress and audit history."""
from alembic import op
import sqlalchemy as sa
revision = "0005_agent_run_events"
down_revision = "0004_agents_automation"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'agent_run_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('message', sa.String(500), nullable=False, server_default=''),
        sa.Column('details_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_agent_run_events_run_id', 'agent_run_events', ['run_id'])
    op.create_index('ix_agent_run_events_run_sequence', 'agent_run_events', ['run_id', 'sequence'])

def downgrade():
    op.drop_index('ix_agent_run_events_run_sequence', table_name='agent_run_events')
    op.drop_index('ix_agent_run_events_run_id', table_name='agent_run_events')
    op.drop_table('agent_run_events')
