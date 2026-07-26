"""One-time proof-of-possession challenge for a device public key."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, TimestampMixin


class DeviceRegistrationChallenge(Base, TimestampMixin):
    __tablename__ = "device_registration_challenges"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('ios', 'android', 'web', 'desktop', 'unknown')",
            name="ck_device_registration_challenges_platform",
        ),
        CheckConstraint(
            "status IN ('pending', 'consumed', 'expired', 'cancelled')",
            name="ck_device_registration_challenges_status",
        ),
        CheckConstraint(
            "octet_length(public_key_fingerprint) = 32",
            name="ck_device_registration_challenges_fingerprint_length",
        ),
        CheckConstraint(
            "octet_length(nonce_digest) = 32",
            name="ck_device_registration_challenges_nonce_digest_length",
        ),
        CheckConstraint(
            "((status = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(status <> 'consumed' AND consumed_at IS NULL))",
            name="ck_device_registration_challenges_consumption",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_device_registration_challenges_expiry",
        ),
        Index("ix_device_registration_challenges_invitation_id", "invitation_id"),
        Index(
            "ix_device_registration_challenges_phone_challenge_id",
            "phone_verification_challenge_id",
        ),
        Index(
            "ix_device_registration_challenges_employee_profile_id",
            "employee_profile_id",
        ),
        Index(
            "ix_device_registration_challenges_public_key_fingerprint",
            "public_key_fingerprint",
        ),
        Index(
            "uq_device_registration_challenges_pending_device",
            "invitation_id",
            "app_instance_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    invitation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("invitations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    phone_verification_challenge_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("phone_verification_challenges.id", ondelete="RESTRICT"),
        nullable=False,
    )
    employee_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("employee_profiles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    app_instance_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    public_key_fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
