"""Add one-time consumption fields to verified phone challenges.

Revision ID: add_phone_challenge_consumption
Revises: add_phone_verification_v1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_phone_challenge_consumption"
down_revision: Union[str, None] = "add_phone_verification_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "phone_verification_challenges",
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "phone_verification_challenges",
        sa.Column("consumed_by_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_phone_verification_challenges_consumed_account",
        "phone_verification_challenges",
        "accounts",
        ["consumed_by_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_consumption_pair",
        "phone_verification_challenges",
        "((consumed_at IS NULL AND consumed_by_account_id IS NULL) OR "
        "(consumed_at IS NOT NULL AND consumed_by_account_id IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_consumed_verified",
        "phone_verification_challenges",
        "consumed_at IS NULL OR status = 'verified'",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_consumed_after_verified",
        "phone_verification_challenges",
        "consumed_at IS NULL OR consumed_at >= verified_at",
    )
    op.create_check_constraint(
        "ck_phone_verification_challenges_consumed_before_updated",
        "phone_verification_challenges",
        "consumed_at IS NULL OR consumed_at <= updated_at",
    )
    op.create_index(
        "ix_phone_verification_challenges_consumed_by_account_id",
        "phone_verification_challenges",
        ["consumed_by_account_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_phone_verification_challenges_consumed_by_account_id",
        table_name="phone_verification_challenges",
    )
    op.drop_constraint(
        "ck_phone_verification_challenges_consumed_before_updated",
        "phone_verification_challenges",
        type_="check",
    )
    op.drop_constraint(
        "ck_phone_verification_challenges_consumed_after_verified",
        "phone_verification_challenges",
        type_="check",
    )
    op.drop_constraint(
        "ck_phone_verification_challenges_consumed_verified",
        "phone_verification_challenges",
        type_="check",
    )
    op.drop_constraint(
        "ck_phone_verification_challenges_consumption_pair",
        "phone_verification_challenges",
        type_="check",
    )
    op.drop_constraint(
        "fk_phone_verification_challenges_consumed_account",
        "phone_verification_challenges",
        type_="foreignkey",
    )
    op.drop_column("phone_verification_challenges", "consumed_by_account_id")
    op.drop_column("phone_verification_challenges", "consumed_at")
