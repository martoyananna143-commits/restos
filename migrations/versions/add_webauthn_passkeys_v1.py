"""Add WebAuthn passkey metadata and one-time ceremony challenges.

Revision ID: add_webauthn_passkeys_v1
Revises: add_assessment_draft_rev
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_webauthn_passkeys_v1"
down_revision: Union[str, None] = "add_assessment_draft_rev"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "account_identities",
        sa.Column("passkey_transports", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "account_identities",
        sa.Column("passkey_backup_eligible", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "account_identities",
        sa.Column("passkey_backup_state", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "account_identities",
        sa.Column("passkey_display_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "account_identities",
        sa.Column(
            "passkey_last_used_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "account_identities",
        sa.Column("passkey_revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "account_identities",
        sa.Column("passkey_revoked_reason", sa.Text(), nullable=True),
    )
    op.drop_constraint(
        "ck_account_identities_type_specific_fields",
        "account_identities",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_identities_type_specific_fields",
        "account_identities",
        "((identity_type IN ('phone', 'email', 'apple', 'telegram') "
        "AND subject_digest IS NOT NULL "
        "AND passkey_credential_id IS NULL "
        "AND passkey_public_key IS NULL "
        "AND sign_count IS NULL "
        "AND passkey_transports IS NULL "
        "AND passkey_backup_eligible IS NULL "
        "AND passkey_backup_state IS NULL "
        "AND passkey_display_name IS NULL "
        "AND passkey_last_used_at IS NULL "
        "AND passkey_revoked_at IS NULL "
        "AND passkey_revoked_reason IS NULL) "
        "OR (identity_type = 'passkey' "
        "AND subject_digest IS NULL "
        "AND subject_ciphertext IS NULL "
        "AND passkey_credential_id IS NOT NULL "
        "AND passkey_public_key IS NOT NULL "
        "AND sign_count IS NOT NULL AND sign_count >= 0 "
        "AND passkey_transports IS NOT NULL "
        "AND passkey_backup_eligible IS NOT NULL "
        "AND passkey_backup_state IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_account_identities_passkey_revocation",
        "account_identities",
        "(identity_type <> 'passkey') OR "
        "((status = 'verified' AND passkey_revoked_at IS NULL "
        "AND passkey_revoked_reason IS NULL) OR "
        "(status IN ('disabled', 'compromised') "
        "AND passkey_revoked_at IS NOT NULL "
        "AND passkey_revoked_reason IS NOT NULL))",
    )
    op.create_check_constraint(
        "ck_account_identities_passkey_transports_array",
        "account_identities",
        "(identity_type <> 'passkey') OR "
        "(jsonb_typeof(passkey_transports) = 'array')",
    )

    op.create_table(
        "account_webauthn_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ceremony_type", sa.String(length=20), nullable=False),
        sa.Column("challenge_digest", sa.LargeBinary(), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("device_context_digest", sa.LargeBinary(), nullable=True),
        sa.Column("app_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=True),
        sa.Column("device_display_name", sa.String(length=255), nullable=True),
        sa.Column("rate_limit_key_digest", sa.LargeBinary(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
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
            "ceremony_type IN ('registration', 'authentication')",
            name="ck_account_webauthn_challenges_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed', 'blocked', 'expired')",
            name="ck_account_webauthn_challenges_status",
        ),
        sa.CheckConstraint(
            "octet_length(challenge_digest) = 32",
            name="ck_account_webauthn_challenges_digest_length",
        ),
        sa.CheckConstraint(
            "rate_limit_key_digest IS NULL "
            "OR octet_length(rate_limit_key_digest) = 32",
            name="ck_account_webauthn_challenges_rate_digest_length",
        ),
        sa.CheckConstraint(
            "device_context_digest IS NULL "
            "OR octet_length(device_context_digest) = 32",
            name="ck_account_webauthn_challenges_device_digest_length",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name="ck_account_webauthn_challenges_attempts"
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_account_webauthn_challenges_expiry",
        ),
        sa.CheckConstraint(
            "((status = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(status <> 'consumed' AND consumed_at IS NULL))",
            name="ck_account_webauthn_challenges_consumption",
        ),
        sa.CheckConstraint(
            "((ceremony_type = 'registration' "
            "AND account_id IS NOT NULL AND session_id IS NOT NULL "
            "AND device_context_digest IS NULL AND app_instance_id IS NULL "
            "AND platform IS NULL AND device_display_name IS NULL) "
            "OR (ceremony_type = 'authentication' "
            "AND account_id IS NULL AND session_id IS NULL "
            "AND device_context_digest IS NOT NULL "
            "AND app_instance_id IS NOT NULL AND platform IS NOT NULL))",
            name="ck_account_webauthn_challenges_binding",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["account_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "challenge_digest",
            name="uq_account_webauthn_challenges_challenge_digest",
        ),
    )
    op.create_index(
        "ix_account_webauthn_challenges_account_id",
        "account_webauthn_challenges",
        ["account_id"],
    )
    op.create_index(
        "ix_account_webauthn_challenges_rate_limit",
        "account_webauthn_challenges",
        ["rate_limit_key_digest", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("account_webauthn_challenges")
    op.drop_constraint(
        "ck_account_identities_passkey_transports_array",
        "account_identities",
        type_="check",
    )
    op.drop_constraint(
        "ck_account_identities_passkey_revocation",
        "account_identities",
        type_="check",
    )
    op.drop_constraint(
        "ck_account_identities_type_specific_fields",
        "account_identities",
        type_="check",
    )
    op.create_check_constraint(
        "ck_account_identities_type_specific_fields",
        "account_identities",
        "((identity_type IN ('phone', 'email', 'apple', 'telegram') "
        "AND subject_digest IS NOT NULL "
        "AND passkey_credential_id IS NULL "
        "AND passkey_public_key IS NULL "
        "AND sign_count IS NULL) "
        "OR (identity_type = 'passkey' "
        "AND subject_digest IS NULL "
        "AND subject_ciphertext IS NULL "
        "AND passkey_credential_id IS NOT NULL "
        "AND passkey_public_key IS NOT NULL "
        "AND sign_count IS NOT NULL AND sign_count >= 0))",
    )
    for column in (
        "passkey_revoked_reason",
        "passkey_revoked_at",
        "passkey_last_used_at",
        "passkey_display_name",
        "passkey_backup_state",
        "passkey_backup_eligible",
        "passkey_transports",
    ):
        op.drop_column("account_identities", column)
