"""Add restricted EmployeeProfile birth-date audit trail.

Revision ID: add_employee_birth_date_audit_v1
Revises: add_private_task_media_v1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_employee_birth_date_audit_v1"
down_revision: str | None = "add_private_task_media_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_employee_profiles_birth_date_min",
        "employee_profiles",
        "birth_date IS NULL OR birth_date >= DATE '1900-01-01'",
    )
    op.create_table(
        "employee_birth_date_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_birth_date", sa.Date(), nullable=True),
        sa.Column("new_birth_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source IN ('group_onboarding','employee_update','manager_update')",
            name="ck_employee_birth_date_audits_source",
        ),
        sa.CheckConstraint(
            "new_birth_date >= DATE '1900-01-01'",
            name="ck_employee_birth_date_audits_min_date",
        ),
        sa.CheckConstraint(
            "previous_birth_date IS DISTINCT FROM new_birth_date",
            name="ck_employee_birth_date_audits_changed",
        ),
        sa.ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_employee_birth_date_audits_profile_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_account_id"], ["accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_employee_birth_date_audits_profile_changed",
        "employee_birth_date_audits",
        ["company_id", "employee_profile_id", "changed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_birth_date_audits_profile_changed",
        table_name="employee_birth_date_audits",
    )
    op.drop_table("employee_birth_date_audits")
    op.drop_constraint(
        "ck_employee_profiles_birth_date_min",
        "employee_profiles",
        type_="check",
    )
