"""Company-specific employee profile model."""

from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin


class EmployeeProfile(Base, TimestampMixin, SoftDeleteMixin):
    """Person card inside one company, separate from assignments."""

    __tablename__ = "employee_profiles"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_employee_profiles_id_company"),
        CheckConstraint(
            "employment_status IN ('invited', 'pending_activation', 'active', 'suspended', 'terminated')",
            name="ck_employee_profiles_status",
        ),
        CheckConstraint(
            "((employment_status = 'terminated' AND terminated_at IS NOT NULL) "
            "OR (employment_status <> 'terminated' AND terminated_at IS NULL))",
            name="ck_employee_profiles_termination_state",
        ),
        CheckConstraint(
            "birth_date IS NULL OR birth_date >= DATE '1900-01-01'",
            name="ck_employee_profiles_birth_date_min",
        ),
        Index(
            "uq_employee_profiles_active_company_account",
            "company_id",
            "account_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND account_id IS NOT NULL"),
        ),
        Index(
            "uq_employee_profiles_active_company_phone",
            "company_id",
            "phone",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND phone IS NOT NULL "
                "AND employment_status <> 'terminated'"
            ),
        ),
        Index("ix_employee_profiles_company_status", "company_id", "employment_status"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    employment_status: Mapped[str] = mapped_column(String(20), nullable=False)
    hired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    terminated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class EmployeeBirthDateAudit(Base):
    """Restricted audit trail for group-onboarding birth-date changes."""

    __tablename__ = "employee_birth_date_audits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_employee_birth_date_audits_profile_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source IN ('group_onboarding','employee_update','manager_update')",
            name="ck_employee_birth_date_audits_source",
        ),
        CheckConstraint(
            "new_birth_date >= DATE '1900-01-01'",
            name="ck_employee_birth_date_audits_min_date",
        ),
        CheckConstraint(
            "previous_birth_date IS DISTINCT FROM new_birth_date",
            name="ck_employee_birth_date_audits_changed",
        ),
        Index(
            "ix_employee_birth_date_audits_profile_changed",
            "company_id",
            "employee_profile_id",
            "changed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    employee_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    previous_birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    new_birth_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
