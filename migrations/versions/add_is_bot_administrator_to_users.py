"""add_is_bot_administrator_to_users

Revision ID: add_is_bot_admin
Revises: 277eb272246b
Create Date: 2025-12-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_is_bot_admin'
down_revision = '277eb272246b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поле is_bot_administrator в таблицу users
    op.add_column(
        'users',
        sa.Column('is_bot_administrator', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    # Удаляем колонку
    op.drop_column('users', 'is_bot_administrator')
