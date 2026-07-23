"""Add account authentication foundation tables.

Revision ID: add_account_auth_foundation
Revises: add_google_sheet_source
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_account_auth_foundation"
down_revision: Union[str, None] = "add_google_sheet_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("pin_hash", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("security_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("security_version >= 1", name="ck_accounts_security_version"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'disabled')", name="ck_accounts_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "account_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_type", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("subject_digest", sa.LargeBinary(), nullable=True),
        sa.Column("subject_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("passkey_credential_id", sa.LargeBinary(), nullable=True),
        sa.Column("passkey_public_key", sa.LargeBinary(), nullable=True),
        sa.Column("sign_count", sa.Integer(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "identity_type IN ('phone', 'email', 'apple', 'telegram', 'passkey')",
            name="ck_account_identities_type",
        ),
        sa.CheckConstraint(
            "provider = lower(provider) "
            "AND provider ~ '^[a-z0-9][a-z0-9._-]{0,99}$'",
            name="ck_account_identities_provider_normalized",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'disabled', 'compromised')",
            name="ck_account_identities_status",
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND verified_at IS NULL) "
            "OR (status IN ('verified', 'disabled', 'compromised') "
            "AND verified_at IS NOT NULL))",
            name="ck_account_identities_verification_state",
        ),
        sa.CheckConstraint(
            "NOT is_primary OR status = 'verified'",
            name="ck_account_identities_primary_verified",
        ),
        sa.CheckConstraint(
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
            name="ck_account_identities_type_specific_fields",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_identities_account_id", "account_identities", ["account_id"], unique=False
    )
    op.create_index(
        "uq_account_identities_active_external",
        "account_identities",
        ["identity_type", "provider", "subject_digest"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND identity_type <> 'passkey'"
        ),
    )
    op.create_index(
        "uq_account_identities_active_passkey_credential",
        "account_identities",
        ["passkey_credential_id"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND identity_type = 'passkey'"
        ),
    )
    op.create_index(
        "uq_account_identities_verified_primary_per_account",
        "account_identities",
        ["account_id"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND status = 'verified' AND is_primary"
        ),
    )

    op.create_table(
        "account_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("app_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("public_key_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("quick_unlock_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "platform IN ('ios', 'android', 'web', 'desktop', 'unknown')",
            name="ck_account_devices_platform",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'disabled')", name="ck_account_devices_status"
        ),
        sa.CheckConstraint(
            "status <> 'revoked' OR revoked_at IS NOT NULL",
            name="ck_account_devices_revoked_at",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", "app_instance_id", name="uq_account_devices_app_instance"
        ),
        sa.UniqueConstraint("id", "account_id", name="uq_account_devices_id_account"),
        sa.UniqueConstraint(
            "public_key_fingerprint", name="uq_account_devices_public_key_fingerprint"
        ),
    )
    op.create_index("ix_account_devices_account_id", "account_devices", ["account_id"])

    op.create_table(
        "account_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_selector", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_secret_digest", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_family", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_rotated_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "issued_at < idle_expires_at",
            name="ck_account_sessions_issued_before_idle_expiry",
        ),
        sa.CheckConstraint(
            "issued_at < absolute_expires_at",
            name="ck_account_sessions_issued_before_absolute_expiry",
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_account_sessions_expiry_order",
        ),
        sa.CheckConstraint(
            "security_version >= 1", name="ck_account_sessions_security_version"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'rotated', 'revoked', 'compromised', 'expired')",
            name="ck_account_sessions_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('revoked', 'compromised') OR revoked_at IS NOT NULL",
            name="ck_account_sessions_revoked_at",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["device_id", "account_id"],
            ["account_devices.id", "account_devices.account_id"],
            name="fk_account_sessions_device_account",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_rotated_session_id"],
            ["account_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_selector", name="uq_account_sessions_token_selector"),
        sa.UniqueConstraint(
            "refresh_secret_digest", name="uq_account_sessions_refresh_secret_digest"
        ),
    )
    op.create_index("ix_account_sessions_account_id", "account_sessions", ["account_id"])
    op.create_index("ix_account_sessions_device_id", "account_sessions", ["device_id"])
    op.create_index(
        "ix_account_sessions_refresh_family", "account_sessions", ["refresh_family"]
    )


def downgrade() -> None:
    op.drop_index("ix_account_sessions_refresh_family", table_name="account_sessions")
    op.drop_index("ix_account_sessions_device_id", table_name="account_sessions")
    op.drop_index("ix_account_sessions_account_id", table_name="account_sessions")
    op.drop_table("account_sessions")
    op.drop_index("ix_account_devices_account_id", table_name="account_devices")
    op.drop_table("account_devices")
    op.drop_index(
        "uq_account_identities_verified_primary_per_account",
        table_name="account_identities",
    )
    op.drop_index(
        "uq_account_identities_active_passkey_credential", table_name="account_identities"
    )
    op.drop_index("uq_account_identities_active_external", table_name="account_identities")
    op.drop_index("ix_account_identities_account_id", table_name="account_identities")
    op.drop_table("account_identities")
    op.drop_table("accounts")
