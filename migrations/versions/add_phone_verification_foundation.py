"""Add provider-neutral phone verification challenge table.

Revision ID: add_phone_verification_foundation
Revises: add_invitation_foundation
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_phone_verification_v1"
down_revision: Union[str, None] = "add_invitation_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "phone_verification_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("phone_digest", sa.LargeBinary(), nullable=False),
        sa.Column("code_digest", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts_used", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resend_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("purpose IN ('invitation_registration', 'login', 'password_reset', 'phone_change')", name="ck_phone_verification_challenges_purpose"),
        sa.CheckConstraint("status IN ('pending', 'verified', 'expired', 'locked', 'cancelled')", name="ck_phone_verification_challenges_status"),
        sa.CheckConstraint("octet_length(phone_digest) = 32", name="ck_phone_verification_challenges_phone_digest_length"),
        sa.CheckConstraint("octet_length(code_digest) = 32", name="ck_phone_verification_challenges_code_digest_length"),
        sa.CheckConstraint("purpose <> 'invitation_registration' OR (invitation_id IS NOT NULL AND employee_profile_id IS NOT NULL)", name="ck_phone_verification_challenges_invitation_context"),
        sa.CheckConstraint("purpose NOT IN ('login', 'phone_change') OR account_id IS NOT NULL", name="ck_phone_verification_challenges_account_context"),
        sa.CheckConstraint("max_attempts > 0 AND attempts_used >= 0 AND attempts_used <= max_attempts", name="ck_phone_verification_challenges_attempts"),
        sa.CheckConstraint("expires_at > created_at", name="ck_phone_verification_challenges_expiry"),
        sa.CheckConstraint("resend_available_at >= created_at", name="ck_phone_verification_challenges_resend"),
        sa.CheckConstraint("((status = 'pending' AND verified_at IS NULL AND locked_at IS NULL AND cancelled_at IS NULL) OR (status = 'verified' AND verified_at IS NOT NULL AND locked_at IS NULL AND cancelled_at IS NULL) OR (status = 'expired' AND verified_at IS NULL AND locked_at IS NULL AND cancelled_at IS NULL) OR (status = 'locked' AND verified_at IS NULL AND locked_at IS NOT NULL AND cancelled_at IS NULL) OR (status = 'cancelled' AND verified_at IS NULL AND locked_at IS NULL AND cancelled_at IS NOT NULL))", name="ck_phone_verification_challenges_state"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invitation_id"], ["invitations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_profile_id"], ["employee_profiles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_phone_verification_challenges_phone_digest", "phone_verification_challenges", ["phone_digest"])
    op.create_index("ix_phone_verification_challenges_account_id", "phone_verification_challenges", ["account_id"])
    op.create_index("ix_phone_verification_challenges_invitation_id", "phone_verification_challenges", ["invitation_id"])
    op.create_index("ix_phone_verification_challenges_employee_profile_id", "phone_verification_challenges", ["employee_profile_id"])
    op.create_index("uq_phone_verification_challenges_active_pending", "phone_verification_challenges", ["purpose", "phone_digest"], unique=True, postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    op.drop_index("uq_phone_verification_challenges_active_pending", table_name="phone_verification_challenges")
    op.drop_index("ix_phone_verification_challenges_employee_profile_id", table_name="phone_verification_challenges")
    op.drop_index("ix_phone_verification_challenges_invitation_id", table_name="phone_verification_challenges")
    op.drop_index("ix_phone_verification_challenges_account_id", table_name="phone_verification_challenges")
    op.drop_index("ix_phone_verification_challenges_phone_digest", table_name="phone_verification_challenges")
    op.drop_table("phone_verification_challenges")
