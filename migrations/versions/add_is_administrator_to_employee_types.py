"""add_is_administrator_to_employee_types

Revision ID: add_is_admin_emp_type
Revises: add_is_bot_admin
Create Date: 2026-03-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_is_admin_emp_type'
down_revision = 'add_is_bot_admin'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'employee_types',
        sa.Column('is_administrator', sa.Boolean(), nullable=False, server_default='false')
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE employee_types SET is_administrator = true WHERE code = 'administrator'"
        )
    )


def downgrade() -> None:
    op.drop_column('employee_types', 'is_administrator')
