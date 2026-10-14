"""add edit_sessions.revision

Revision ID: c3a9f1b52e07
Revises: 7b4e2c81f0a9
Create Date: 2026-10-14 17:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3a9f1b52e07'
down_revision: Union[str, None] = '7b4e2c81f0a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # 已有会话需要有初始值：server_default 让存量行直接变成 0（= 初始状态）
    op.add_column(
        'edit_sessions',
        sa.Column('revision', sa.Integer(), server_default='0', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('edit_sessions', 'revision')
