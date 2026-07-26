"""Add one-time device proof-of-possession challenges.

Revision ID: add_device_proof_v1
Revises: add_phone_challenge_consumption
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_device_proof_v1"
down_revision: Union[str, None] = "add_phone_challenge_consumption"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "device_registration_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "phone_verification_challenge_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("employee_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("app_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("public_key_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("nonce_digest", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "platform IN ('ios', 'android', 'web', 'desktop', 'unknown')",
            name="ck_device_registration_challenges_platform",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'expired', 'cancelled')",
            name="ck_device_registration_challenges_status",
        ),
        sa.CheckConstraint(
            "octet_length(public_key_fingerprint) = 32",
            name="ck_device_registration_challenges_fingerprint_length",
        ),
        sa.CheckConstraint(
            "octet_length(nonce_digest) = 32",
            name="ck_device_registration_challenges_nonce_digest_length",
        ),
        sa.CheckConstraint(
            "((status = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(status <> 'consumed' AND consumed_at IS NULL))",
            name="ck_device_registration_challenges_consumption",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_device_registration_challenges_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["invitations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["phone_verification_challenge_id"],
            ["phone_verification_challenges.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["employee_profile_id"], ["employee_profiles.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_device_registration_challenges_invitation_id",
        "device_registration_challenges",
        ["invitation_id"],
    )
    op.create_index(
        "ix_device_registration_challenges_phone_challenge_id",
        "device_registration_challenges",
        ["phone_verification_challenge_id"],
    )
    op.create_index(
        "ix_device_registration_challenges_employee_profile_id",
        "device_registration_challenges",
        ["employee_profile_id"],
    )
    op.create_index(
        "ix_device_registration_challenges_public_key_fingerprint",
        "device_registration_challenges",
        ["public_key_fingerprint"],
    )
    op.create_index(
        "uq_device_registration_challenges_pending_device",
        "device_registration_challenges",
        ["invitation_id", "app_instance_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("device_registration_challenges")
