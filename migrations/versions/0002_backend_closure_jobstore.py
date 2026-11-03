"""Persisted scheduler jobstore; API runs without schema auto-creation."""
from alembic import op
import sqlalchemy as sa

revision = '0002_backend_closure'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('apscheduler_jobs',
        sa.Column('id', sa.Unicode(191), primary_key=True),
        sa.Column('next_run_time', sa.Float(25), nullable=True),
        sa.Column('job_state', sa.LargeBinary(), nullable=False))
    op.create_index('ix_apscheduler_jobs_next_run_time', 'apscheduler_jobs', ['next_run_time'])


def downgrade():
    op.drop_index('ix_apscheduler_jobs_next_run_time', table_name='apscheduler_jobs')
    op.drop_table('apscheduler_jobs')
