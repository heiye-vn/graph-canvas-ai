"""add agent_traces

Revision ID: d9f3e5b72c41
Revises: b7e2d4a91c30
Create Date: 2026-10-15 16:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'd9f3e5b72c41'
down_revision: Union[str, None] = 'b7e2d4a91c30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        'agent_traces',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('agent_run_id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('status', sa.String(length=8), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('prompt_version', sa.String(length=40), nullable=True),
        sa.Column('model', sa.String(length=80), nullable=True),
        sa.Column('tokens_in', sa.Integer(), nullable=True),
        sa.Column('tokens_out', sa.Integer(), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_agent_traces_agent_run_id', 'agent_traces', ['agent_run_id'], unique=False)
    op.create_index('ix_agent_traces_session_id', 'agent_traces', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_agent_traces_session_id', table_name='agent_traces')
    op.drop_index('ix_agent_traces_agent_run_id', table_name='agent_traces')
    op.drop_table('agent_traces')
