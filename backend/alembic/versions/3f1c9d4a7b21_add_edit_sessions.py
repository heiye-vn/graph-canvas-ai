"""add edit_sessions

Revision ID: 3f1c9d4a7b21
Revises: 210aec10e787
Create Date: 2026-10-13 15:55:00.000000

"""

from typing import Sequence, Union

from sqlalchemy.dialects import postgresql

from alembic import op
import sqlalchemy as sa

revision: str = '3f1c9d4a7b21'
down_revision: Union[str, None] = '210aec10e787'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'edit_sessions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('doc', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_edit_sessions_user_id', 'edit_sessions', ['user_id'], unique=False)

    op.create_table(
        'session_assets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('asset_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['edit_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'asset_id', name='uq_session_asset'),
    )
    op.create_index('ix_session_assets_session_id', 'session_assets', ['session_id'], unique=False)
    op.create_index('ix_session_assets_asset_id', 'session_assets', ['asset_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_session_assets_asset_id', table_name='session_assets')
    op.drop_index('ix_session_assets_session_id', table_name='session_assets')
    op.drop_table('session_assets')
    op.drop_index('ix_edit_sessions_user_id', table_name='edit_sessions')
    op.drop_table('edit_sessions')
