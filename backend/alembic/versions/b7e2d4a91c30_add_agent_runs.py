"""add agent_runs

Revision ID: b7e2d4a91c30
Revises: c3a9f1b52e07
Create Date: 2026-10-15 14:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b7e2d4a91c30'
down_revision: Union[str, None] = 'c3a9f1b52e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        'agent_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('instruction', sa.String(length=1000), nullable=False),
        sa.Column('plan', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('reply', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['edit_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_runs_user_id', 'agent_runs', ['user_id'], unique=False)
    op.create_index('ix_agent_runs_session_id', 'agent_runs', ['session_id'], unique=False)
    op.create_index('ix_agent_runs_status', 'agent_runs', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_agent_runs_status', table_name='agent_runs')
    op.drop_index('ix_agent_runs_session_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_user_id', table_name='agent_runs')
    op.drop_table('agent_runs')
