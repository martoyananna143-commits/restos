"""add_current_organization_id_to_users

Revision ID: add_current_org_id
Revises: add_is_bot_admin
Create Date: 2025-02-24 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_current_org_id'
down_revision = 'add_is_bot_admin'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('current_organization_id', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('users', 'current_organization_id')
