"""merge_heads

Revision ID: 768843a2dc51
Revises: add_criterion_value_types, add_current_org_id, add_is_admin_emp_type, add_org_to_eval_types
Create Date: 2026-03-19 20:00:16.843375

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '768843a2dc51'
down_revision = ('add_criterion_value_types', 'add_current_org_id', 'add_is_admin_emp_type', 'add_org_to_eval_types')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
