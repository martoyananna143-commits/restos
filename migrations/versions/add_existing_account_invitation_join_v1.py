"""Scope active employee phone uniqueness to one Company.

Revision ID: add_account_invite_join_v1
Revises: add_assessment_metrics_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "add_account_invite_join_v1"
down_revision: Union[str, None] = "add_assessment_metrics_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_employee_profiles_active_company_phone",
        "employee_profiles",
        ["company_id", "phone"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND phone IS NOT NULL "
            "AND employment_status <> 'terminated'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_employee_profiles_active_company_phone",
        table_name="employee_profiles",
    )
