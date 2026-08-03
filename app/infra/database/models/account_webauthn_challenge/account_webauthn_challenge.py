"""One-time server-side WebAuthn ceremony state."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, TimestampMixin


class AccountWebAuthnChallenge(Base, TimestampMixin):
    __tablename__ = "account_webauthn_challenges"
    __table_args__ = (
        CheckConstraint(
            "ceremony_type IN ('registration', 'authentication')",
            name="ck_account_webauthn_challenges_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'consumed', 'blocked', 'expired')",
            name="ck_account_webauthn_challenges_status",
        ),
        CheckConstraint(
            "octet_length(challenge_digest) = 32",
            name="ck_account_webauthn_challenges_digest_length",
        ),
        CheckConstraint(
            "rate_limit_key_digest IS NULL "
            "OR octet_length(rate_limit_key_digest) = 32",
            name="ck_account_webauthn_challenges_rate_digest_length",
        ),
        CheckConstraint(
            "device_context_digest IS NULL "
            "OR octet_length(device_context_digest) = 32",
            name="ck_account_webauthn_challenges_device_digest_length",
        ),
        CheckConstraint(
            "attempts >= 0", name="ck_account_webauthn_challenges_attempts"
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_account_webauthn_challenges_expiry",
        ),
        CheckConstraint(
            "((status = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(status <> 'consumed' AND consumed_at IS NULL))",
            name="ck_account_webauthn_challenges_consumption",
        ),
        CheckConstraint(
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
        UniqueConstraint(
            "challenge_digest",
            name="uq_account_webauthn_challenges_challenge_digest",
        ),
        Index(
            "ix_account_webauthn_challenges_account_id",
            "account_id",
        ),
        Index(
            "ix_account_webauthn_challenges_rate_limit",
            "rate_limit_key_digest",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ceremony_type: Mapped[str] = mapped_column(String(20), nullable=False)
    challenge_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    session_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("account_sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    device_context_digest: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    app_instance_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    platform: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    device_display_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    rate_limit_key_digest: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
