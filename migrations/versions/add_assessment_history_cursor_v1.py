"""Add stable cursor index for immutable assessment history.

Revision ID: add_assessment_history_cursor_v1
Revises: add_employee_birth_date_audit_v1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "add_assessment_history_cursor_v1"
down_revision: str | None = "add_employee_birth_date_audit_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_assessment_attempts_submitted_cursor",
        "assessment_attempts",
        ["submitted_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'submitted'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_assessment_attempts_submitted_cursor",
        table_name="assessment_attempts",
    )
