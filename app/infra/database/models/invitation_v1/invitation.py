"""Secure employee invitation and venue join models."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin


class Invitation(Base, TimestampMixin, SoftDeleteMixin):
    """Pending workforce invitation with an HMAC-only six-digit code digest."""

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_invitations_id_company"),
        ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_invitations_profile_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["position_id", "company_id"],
            ["positions.id", "positions.company_id"],
            name="fk_invitations_position_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_invitations_access_profile_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["accepted_assignment_id", "company_id"],
            ["employee_assignments.id", "employee_assignments.company_id"],
            name="fk_invitations_assignment_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "scope_type IN ('self', 'working_venues', 'explicit_venues', 'company')",
            name="ck_invitations_scope_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'cancelled', 'expired')",
            name="ck_invitations_status",
        ),
        CheckConstraint(
            "delivery_status IN ('delivery_pending', 'sent', 'unknown', 'failed')",
            name="ck_invitations_delivery_status",
        ),
        CheckConstraint(
            "delivery_attempt_count >= 0",
            name="ck_invitations_delivery_attempt_count",
        ),
        CheckConstraint(
            "delivery_attempt_count = 0 OR delivery_attempted_at IS NOT NULL",
            name="ck_invitations_delivery_attempted_state",
        ),
        CheckConstraint(
            "((delivery_status = 'sent' AND delivery_sent_at IS NOT NULL) OR "
            "(delivery_status <> 'sent' AND delivery_sent_at IS NULL))",
            name="ck_invitations_delivery_sent_state",
        ),
        CheckConstraint(
            "octet_length(code_digest) = 32",
            name="ck_invitations_code_digest_length",
        ),
        CheckConstraint(
            "("
            "(status = 'pending' AND accepted_by_account_id IS NULL "
            "AND accepted_assignment_id IS NULL AND accepted_at IS NULL "
            "AND cancelled_at IS NULL AND cancelled_by_account_id IS NULL "
            "AND cancel_reason IS NULL) OR "
            "(status = 'accepted' AND accepted_by_account_id IS NOT NULL "
            "AND accepted_assignment_id IS NOT NULL AND accepted_at IS NOT NULL "
            "AND cancelled_at IS NULL AND cancelled_by_account_id IS NULL "
            "AND cancel_reason IS NULL) OR "
            "(status = 'cancelled' AND accepted_by_account_id IS NULL "
            "AND accepted_assignment_id IS NULL AND accepted_at IS NULL "
            "AND cancelled_at IS NOT NULL AND cancelled_by_account_id IS NOT NULL) OR "
            "(status = 'expired' AND accepted_by_account_id IS NULL "
            "AND accepted_assignment_id IS NULL AND accepted_at IS NULL "
            "AND cancelled_at IS NULL AND cancelled_by_account_id IS NULL "
            "AND cancel_reason IS NULL)"
            ")",
            name="ck_invitations_state",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_invitations_expiry",
        ),
        CheckConstraint(
            "accepted_at IS NULL OR (accepted_at >= created_at "
            "AND accepted_at <= expires_at)",
            name="ck_invitations_accepted_at",
        ),
        CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= created_at",
            name="ck_invitations_cancelled_at",
        ),
        Index("ix_invitations_company_id", "company_id"),
        Index("ix_invitations_employee_profile_id", "employee_profile_id"),
        Index("ix_invitations_status", "status"),
        Index("ix_invitations_company_delivery", "company_id", "delivery_status"),
        Index("ix_invitations_expires_at", "expires_at"),
        Index("ix_invitations_created_by_account_id", "created_by_account_id"),
        Index(
            "uq_invitations_active_code_digest",
            "code_digest",
            unique=True,
            postgresql_where=text("status = 'pending' AND deleted_at IS NULL"),
        ),
        Index(
            "uq_invitations_pending_employee_profile",
            "employee_profile_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND deleted_at IS NULL"),
        ),
        Index(
            "uq_invitations_accepted_assignment",
            "accepted_assignment_id",
            unique=True,
            postgresql_where=text("accepted_assignment_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    employee_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    access_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    code_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown"
    )
    delivery_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    delivery_attempted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accepted_by_account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    accepted_assignment_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by_account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class InvitationVenue(Base):
    """Venue where the invited employee will work."""

    __tablename__ = "invitation_venues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "company_id"],
            ["invitations.id", "invitations.company_id"],
            name="fk_invitation_venues_invitation_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_invitation_venues_venue_company",
            ondelete="RESTRICT",
        ),
        Index("ix_invitation_venues_venue_invitation", "venue_id", "invitation_id"),
    )

    invitation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class InvitationScopeVenue(Base):
    """Venue visible through the invitation's explicit scope."""

    __tablename__ = "invitation_scope_venues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "company_id"],
            ["invitations.id", "invitations.company_id"],
            name="fk_invitation_scope_venues_invitation_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_invitation_scope_venues_venue_company",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_invitation_scope_venues_venue_invitation",
            "venue_id",
            "invitation_id",
        ),
    )

    invitation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
