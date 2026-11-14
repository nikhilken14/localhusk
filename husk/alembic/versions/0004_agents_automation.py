"""Add MCP connections, agent runs/approvals, and automation definitions."""
from alembic import op
import sqlalchemy as sa
revision = "0004_agents_automation"
down_revision = "0003_productivity"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('mcp_servers', sa.Column('id',sa.String(36),primary_key=True), sa.Column('name',sa.String(120),nullable=False), sa.Column('transport',sa.String(20),nullable=False), sa.Column('command',sa.String(500),nullable=False), sa.Column('args_json',sa.Text(),nullable=False), sa.Column('url',sa.String(1000),nullable=False), sa.Column('enabled',sa.Boolean(),nullable=False), sa.Column('require_approval',sa.Boolean(),nullable=False), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('agent_runs', sa.Column('id',sa.String(36),primary_key=True), sa.Column('goal',sa.Text(),nullable=False), sa.Column('status',sa.String(20),nullable=False), sa.Column('result',sa.Text(),nullable=False), sa.Column('error',sa.Text(),nullable=False), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False), sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('agent_approvals', sa.Column('id',sa.String(36),primary_key=True), sa.Column('run_id',sa.String(36),nullable=False), sa.Column('action',sa.String(120),nullable=False), sa.Column('details',sa.Text(),nullable=False), sa.Column('status',sa.String(20),nullable=False), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False), sa.Column('decided_at',sa.DateTime(timezone=True)), sa.ForeignKeyConstraint(['run_id'],['agent_runs.id'],ondelete='CASCADE'))
    op.create_index('ix_agent_approvals_run_id','agent_approvals',['run_id'])
    op.create_table('automation_jobs', sa.Column('id',sa.String(36),primary_key=True), sa.Column('name',sa.String(160),nullable=False), sa.Column('description',sa.Text(),nullable=False), sa.Column('trigger_type',sa.String(20),nullable=False), sa.Column('trigger_config',sa.Text(),nullable=False), sa.Column('enabled',sa.Boolean(),nullable=False), sa.Column('run_count',sa.Integer(),nullable=False), sa.Column('last_run_at',sa.DateTime(timezone=True)), sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))

def downgrade():
    op.drop_table('automation_jobs'); op.drop_index('ix_agent_approvals_run_id',table_name='agent_approvals'); op.drop_table('agent_approvals'); op.drop_table('agent_runs'); op.drop_table('mcp_servers')
