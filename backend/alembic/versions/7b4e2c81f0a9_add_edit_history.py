"""add edit_history

Revision ID: 7b4e2c81f0a9
Revises: 3f1c9d4a7b21
Create Date: 2026-10-14 10:30:00.000000

"""

from typing import Sequence, Union

from sqlalchemy.dialects import postgresql

from alembic import op
import sqlalchemy as sa

revision: str = '7b4e2c81f0a9'
down_revision: Union[str, None] = '3f1c9d4a7b21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # 已有会话需要有初始值：server_default 让存量行直接变成 0（= 初始状态）
    op.add_column(
        'edit_sessions',
        sa.Column('history_seq', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('edit_sessions', 'history_seq', server_default=None)

    op.create_table(
        'edit_history',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('tool', sa.String(length=64), nullable=True),
        sa.Column('label', sa.String(length=64), nullable=False),
        sa.Column('changed', sa.Boolean(), nullable=False),
        sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['edit_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'seq', name='uq_history_seq'),
    )
    op.create_index('ix_edit_history_session_id', 'edit_history', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_edit_history_session_id', table_name='edit_history')
    op.drop_table('edit_history')
    op.drop_column('edit_sessions', 'history_seq')
