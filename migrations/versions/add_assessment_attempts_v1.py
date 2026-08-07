"""Add assigned employee assessment attempts and answers.

Revision ID: add_assessment_attempts_v1
Revises: add_webauthn_passkeys_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_assessment_attempts_v1"
down_revision: Union[str, None] = "add_webauthn_passkeys_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assessment_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_employee_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(20), server_default="assigned", nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('assigned', 'in_progress', 'completed', 'revoked')", name="ck_assessment_assignments_status"),
        sa.CheckConstraint("due_at IS NULL OR due_at > assigned_at", name="ck_assessment_assignments_due_after_assigned"),
        sa.CheckConstraint("((status = 'revoked' AND revoked_at IS NOT NULL AND completed_at IS NULL) OR (status = 'completed' AND completed_at IS NOT NULL AND revoked_at IS NULL) OR (status IN ('assigned', 'in_progress') AND revoked_at IS NULL AND completed_at IS NULL))", name="ck_assessment_assignments_state_timestamps"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_profile_id"], ["employee_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_version_id"], ["assessment_template_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_employee_profile_id"], ["employee_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assessment_assignments_employee_status", "assessment_assignments", ["employee_profile_id", "status"])
    op.create_index("ix_assessment_assignments_company_status", "assessment_assignments", ["company_id", "status"])
    op.create_index("ix_assessment_assignments_due_at", "assessment_assignments", ["due_at"])

    op.create_table(
        "assessment_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'submitted')", name="ck_assessment_attempts_status"),
        sa.CheckConstraint("revision >= 0", name="ck_assessment_attempts_revision"),
        sa.CheckConstraint("((status = 'draft' AND submitted_at IS NULL AND result_json IS NULL) OR (status = 'submitted' AND submitted_at IS NOT NULL AND result_json IS NOT NULL))", name="ck_assessment_attempts_submission_state"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assessment_assignments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_profile_id"], ["employee_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["template_version_id"], ["assessment_template_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", name="uq_assessment_attempts_assignment_id"),
    )
    op.create_index("ix_assessment_attempts_account_status", "assessment_attempts", ["account_id", "status"])
    op.create_index("ix_assessment_attempts_employee_status", "assessment_attempts", ["employee_profile_id", "status"])

    op.create_table(
        "assessment_attempt_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answer_type", sa.String(30), nullable=False),
        sa.Column("value_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("answer_type IN ('boolean', 'score', 'integer', 'decimal', 'text', 'single_choice', 'multi_choice', 'date', 'time')", name="ck_assessment_attempt_answers_type"),
        sa.ForeignKeyConstraint(["attempt_id"], ["assessment_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["assessment_template_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "item_id", name="uq_assessment_attempt_answers_attempt_item"),
    )
    op.create_index("ix_assessment_attempt_answers_attempt_id", "assessment_attempt_answers", ["attempt_id"])


def downgrade() -> None:
    op.drop_table("assessment_attempt_answers")
    op.drop_table("assessment_attempts")
    op.drop_table("assessment_assignments")
