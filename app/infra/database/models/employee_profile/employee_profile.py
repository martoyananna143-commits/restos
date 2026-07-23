"""Company-specific employee profile model."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin


class EmployeeProfile(Base, TimestampMixin, SoftDeleteMixin):
    """Person card inside one company, separate from assignments."""

    __tablename__ = "employee_profiles"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_employee_profiles_id_company"),
        CheckConstraint(
            "employment_status IN ('invited', 'active', 'suspended', 'terminated')",
            name="ck_employee_profiles_status",
        ),
        CheckConstraint(
            "((employment_status = 'terminated' AND terminated_at IS NOT NULL) "
            "OR (employment_status <> 'terminated' AND terminated_at IS NULL))",
            name="ck_employee_profiles_termination_state",
        ),
        Index(
            "uq_employee_profiles_active_company_account",
            "company_id",
            "account_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND account_id IS NOT NULL"),
        ),
        Index(
            "ix_employee_profiles_company_status", "company_id", "employment_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
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
