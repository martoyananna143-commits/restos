"""Add Account-scoped assessment management invariants.

Revision ID: add_assessment_management_v1
Revises: add_assessment_attempts_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_assessment_management_v1"
down_revision: Union[str, None] = "add_assessment_attempts_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assessment_assignments",
        sa.Column("assigned_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_assessment_assignments_assigned_by_account",
        "assessment_assignments",
        "accounts",
        ["assigned_by_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_assessment_assignments_active_employee_version",
        "assessment_assignments",
        ["company_id", "employee_profile_id", "template_version_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('assigned', 'in_progress')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_assessment_assignments_active_employee_version",
        table_name="assessment_assignments",
    )
    op.drop_constraint(
        "fk_assessment_assignments_assigned_by_account",
        "assessment_assignments",
        type_="foreignkey",
    )
    op.drop_column("assessment_assignments", "assigned_by_account_id")
