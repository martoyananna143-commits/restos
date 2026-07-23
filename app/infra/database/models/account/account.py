"""Additive-only account authentication foundation."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin


class Account(Base, TimestampMixin, SoftDeleteMixin):
    """Authentication subject, intentionally separate from legacy User/Employee."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'disabled')",
            name="ck_accounts_status",
        ),
        CheckConstraint("security_version >= 1", name="ck_accounts_security_version"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pin_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    security_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AccountIdentity(Base, TimestampMixin, SoftDeleteMixin):
    """Normalized external identity or passkey belonging to an account."""

    __tablename__ = "account_identities"
    __table_args__ = (
        CheckConstraint(
            "identity_type IN ('phone', 'email', 'apple', 'telegram', 'passkey')",
            name="ck_account_identities_type",
        ),
        CheckConstraint(
            "provider = lower(provider) "
            "AND provider ~ '^[a-z0-9][a-z0-9._-]{0,99}$'",
            name="ck_account_identities_provider_normalized",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'disabled', 'compromised')",
            name="ck_account_identities_status",
        ),
        CheckConstraint(
            "((status = 'pending' AND verified_at IS NULL) "
            "OR (status IN ('verified', 'disabled', 'compromised') "
            "AND verified_at IS NOT NULL))",
            name="ck_account_identities_verification_state",
        ),
        CheckConstraint(
            "NOT is_primary OR status = 'verified'",
            name="ck_account_identities_primary_verified",
        ),
        CheckConstraint(
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
        Index(
            "uq_account_identities_active_external",
            "identity_type",
            "provider",
            "subject_digest",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND identity_type <> 'passkey'"
            ),
        ),
        Index(
            "uq_account_identities_active_passkey_credential",
            "passkey_credential_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND identity_type = 'passkey'"
            ),
        ),
        Index(
            "uq_account_identities_verified_primary_per_account",
            "account_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status = 'verified' AND is_primary"
            ),
        ),
        Index("ix_account_identities_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_digest: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    subject_ciphertext: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    passkey_credential_id: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    passkey_public_key: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    sign_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    identity_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class AccountDevice(Base, TimestampMixin):
    """App-created device identity without hardware fingerprinting."""

    __tablename__ = "account_devices"
    __table_args__ = (
        UniqueConstraint("id", "account_id", name="uq_account_devices_id_account"),
        UniqueConstraint(
            "account_id", "app_instance_id", name="uq_account_devices_app_instance"
        ),
        UniqueConstraint(
            "public_key_fingerprint", name="uq_account_devices_public_key_fingerprint"
        ),
        CheckConstraint(
            "platform IN ('ios', 'android', 'web', 'desktop', 'unknown')",
            name="ck_account_devices_platform",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked', 'disabled')",
            name="ck_account_devices_status",
        ),
        CheckConstraint(
            "status <> 'revoked' OR revoked_at IS NOT NULL",
            name="ck_account_devices_revoked_at",
        ),
        Index("ix_account_devices_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    app_instance_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    public_key_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    quick_unlock_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AccountSession(Base, TimestampMixin):
    """Rotating refresh session bound to one account-owned device."""

    __tablename__ = "account_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["device_id", "account_id"],
            ["account_devices.id", "account_devices.account_id"],
            name="fk_account_sessions_device_account",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('active', 'rotated', 'revoked', 'compromised', 'expired')",
            name="ck_account_sessions_status",
        ),
        CheckConstraint(
            "security_version >= 1", name="ck_account_sessions_security_version"
        ),
        CheckConstraint(
            "issued_at < idle_expires_at",
            name="ck_account_sessions_issued_before_idle_expiry",
        ),
        CheckConstraint(
            "issued_at < absolute_expires_at",
            name="ck_account_sessions_issued_before_absolute_expiry",
        ),
        CheckConstraint(
            "idle_expires_at <= absolute_expires_at",
            name="ck_account_sessions_expiry_order",
        ),
        CheckConstraint(
            "status NOT IN ('revoked', 'compromised') OR revoked_at IS NOT NULL",
            name="ck_account_sessions_revoked_at",
        ),
        UniqueConstraint("token_selector", name="uq_account_sessions_token_selector"),
        UniqueConstraint(
            "refresh_secret_digest", name="uq_account_sessions_refresh_secret_digest"
        ),
        Index("ix_account_sessions_account_id", "account_id"),
        Index("ix_account_sessions_device_id", "device_id"),
        Index("ix_account_sessions_refresh_family", "refresh_family"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token_selector: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    refresh_secret_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_family: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    previous_rotated_session_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("account_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    security_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
