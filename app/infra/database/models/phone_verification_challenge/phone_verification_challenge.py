"""Provider-neutral SMS phone verification challenge model."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, TimestampMixin


class PhoneVerificationChallenge(Base, TimestampMixin):
    """Immutable-history OTP challenge; plaintext phone and code are never stored."""

    __tablename__ = "phone_verification_challenges"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('invitation_registration', 'account_registration', 'login', 'password_reset', 'phone_change')",
            name="ck_phone_verification_challenges_purpose",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'expired', 'locked', 'cancelled')",
            name="ck_phone_verification_challenges_status",
        ),
        CheckConstraint(
            "octet_length(phone_digest) = 32",
            name="ck_phone_verification_challenges_phone_digest_length",
        ),
        CheckConstraint(
            "octet_length(code_digest) = 32",
            name="ck_phone_verification_challenges_code_digest_length",
        ),
        CheckConstraint(
            "purpose <> 'invitation_registration' OR "
            "(invitation_id IS NOT NULL AND employee_profile_id IS NOT NULL)",
            name="ck_phone_verification_challenges_invitation_context",
        ),
        CheckConstraint(
            "purpose NOT IN ('login', 'phone_change') OR account_id IS NOT NULL",
            name="ck_phone_verification_challenges_account_context",
        ),
        CheckConstraint(
            "max_attempts > 0 AND attempts_used >= 0 AND attempts_used <= max_attempts",
            name="ck_phone_verification_challenges_attempts",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_phone_verification_challenges_expiry",
        ),
        CheckConstraint(
            "resend_available_at >= created_at",
            name="ck_phone_verification_challenges_resend",
        ),
        CheckConstraint(
            "((status = 'pending' AND verified_at IS NULL AND locked_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'verified' AND verified_at IS NOT NULL AND locked_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'expired' AND verified_at IS NULL AND locked_at IS NULL AND cancelled_at IS NULL) OR "
            "(status = 'locked' AND verified_at IS NULL AND locked_at IS NOT NULL AND cancelled_at IS NULL) OR "
            "(status = 'cancelled' AND verified_at IS NULL AND locked_at IS NULL AND cancelled_at IS NOT NULL))",
            name="ck_phone_verification_challenges_state",
        ),
        CheckConstraint(
            "((consumed_at IS NULL AND consumed_by_account_id IS NULL) OR "
            "(consumed_at IS NOT NULL AND consumed_by_account_id IS NOT NULL))",
            name="ck_phone_verification_challenges_consumption_pair",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR status = 'verified'",
            name="ck_phone_verification_challenges_consumed_verified",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= verified_at",
            name="ck_phone_verification_challenges_consumed_after_verified",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at <= updated_at",
            name="ck_phone_verification_challenges_consumed_before_updated",
        ),
        CheckConstraint(
            "pd_consent_document_sha256 IS NULL OR octet_length(pd_consent_document_sha256) = 32",
            name="ck_phone_verification_challenges_pd_consent_hash",
        ),
        CheckConstraint(
            "auth_sms_consent_copy_sha256 IS NULL OR octet_length(auth_sms_consent_copy_sha256) = 32",
            name="ck_phone_verification_challenges_sms_consent_hash",
        ),
        CheckConstraint(
            "auth_sms_message_type IS NULL OR auth_sms_message_type IN ('registration_otp', 'password_recovery_otp')",
            name="ck_phone_verification_challenges_sms_message_type",
        ),
        CheckConstraint(
            "((pd_consent_version IS NULL AND pd_consent_document_sha256 IS NULL AND pd_consent_accepted_at IS NULL) OR "
            "(pd_consent_version IS NOT NULL AND pd_consent_document_sha256 IS NOT NULL AND pd_consent_accepted_at IS NOT NULL))",
            name="ck_phone_verification_challenges_pd_consent_complete",
        ),
        CheckConstraint(
            "((auth_sms_consent_version IS NULL AND auth_sms_consent_copy_sha256 IS NULL AND auth_sms_consent_accepted_at IS NULL AND auth_sms_message_type IS NULL) OR "
            "(auth_sms_consent_version IS NOT NULL AND auth_sms_consent_copy_sha256 IS NOT NULL AND auth_sms_consent_accepted_at IS NOT NULL AND auth_sms_message_type IS NOT NULL))",
            name="ck_phone_verification_challenges_sms_consent_complete",
        ),
        Index("ix_phone_verification_challenges_phone_digest", "phone_digest"),
        Index("ix_phone_verification_challenges_account_id", "account_id"),
        Index("ix_phone_verification_challenges_invitation_id", "invitation_id"),
        Index("ix_phone_verification_challenges_employee_profile_id", "employee_profile_id"),
        Index("ix_phone_verification_challenges_consumed_by_account_id", "consumed_by_account_id"),
        Index(
            "uq_phone_verification_challenges_active_pending",
            "purpose",
            "phone_digest",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    invitation_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("invitations.id", ondelete="RESTRICT"), nullable=True
    )
    employee_profile_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    phone_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    code_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts_used: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resend_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    pd_consent_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pd_consent_document_sha256: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    pd_consent_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auth_sms_consent_version: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    auth_sms_consent_copy_sha256: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    auth_sms_consent_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auth_sms_message_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
