"""Employee assignment and venue join models."""

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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin


class EmployeeAssignment(Base, TimestampMixin, SoftDeleteMixin):
    """Position, access profile, and visibility scope assigned to a person."""

    __tablename__ = "employee_assignments"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_employee_assignments_id_company"),
        UniqueConstraint(
            "legacy_employee_id", name="uq_employee_assignments_legacy_employee_id"
        ),
        ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_employee_assignments_profile_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["position_id", "company_id"],
            ["positions.id", "positions.company_id"],
            name="fk_employee_assignments_position_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_employee_assignments_access_profile_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "scope_type IN ('self', 'working_venues', 'explicit_venues', 'company')",
            name="ck_employee_assignments_scope_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'ended', 'revoked')",
            name="ck_employee_assignments_status",
        ),
        CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at",
            name="ck_employee_assignments_dates",
        ),
        CheckConstraint(
            "status <> 'ended' OR ends_at IS NOT NULL",
            name="ck_employee_assignments_ended_at",
        ),
        CheckConstraint(
            "status <> 'revoked' OR (revoked_at IS NOT NULL "
            "AND revoked_by_account_id IS NOT NULL)",
            name="ck_employee_assignments_revoked_state",
        ),
        CheckConstraint(
            "status = 'revoked' OR (revoked_at IS NULL "
            "AND revoked_by_account_id IS NULL AND revoke_reason IS NULL)",
            name="ck_employee_assignments_non_revoked_state",
        ),
        CheckConstraint(
            "NOT is_primary OR status = 'active'",
            name="ck_employee_assignments_primary_active",
        ),
        Index(
            "uq_employee_assignments_active_primary_profile",
            "employee_profile_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND status = 'active' AND is_primary"
            ),
        ),
        Index("ix_employee_assignments_company_id", "company_id"),
        Index("ix_employee_assignments_employee_profile_id", "employee_profile_id"),
        Index("ix_employee_assignments_position_id", "position_id"),
        Index("ix_employee_assignments_access_profile_id", "access_profile_id"),
        Index("ix_employee_assignments_status", "status"),
        Index("ix_employee_assignments_legacy_employee_id", "legacy_employee_id"),
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
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    legacy_employee_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=True,
    )


class AssignmentVenue(Base):
    """Venue where the assignment holder works."""

    __tablename__ = "assignment_venues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_id", "company_id"],
            ["employee_assignments.id", "employee_assignments.company_id"],
            name="fk_assignment_venues_assignment_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assignment_venues_venue_company",
            ondelete="RESTRICT",
        ),
        Index("ix_assignment_venues_venue_assignment", "venue_id", "assignment_id"),
    )

    assignment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AssignmentScopeVenue(Base):
    """Venue visible through an explicit-venues assignment scope."""

    __tablename__ = "assignment_scope_venues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_id", "company_id"],
            ["employee_assignments.id", "employee_assignments.company_id"],
            name="fk_assignment_scope_venues_assignment_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_assignment_scope_venues_venue_company",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_assignment_scope_venues_venue_assignment", "venue_id", "assignment_id"
        ),
    )

    assignment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
