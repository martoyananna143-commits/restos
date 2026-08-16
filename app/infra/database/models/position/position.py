"""Company-specific business position model."""

from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin


class Position(Base, TimestampMixin, SoftDeleteMixin):
    """Business position, distinct from its optional default access profile."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_positions_id_company"),
        ForeignKeyConstraint(
            ["default_access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_positions_default_profile_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "code = lower(code) AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_positions_code_slug",
        ),
        CheckConstraint("sort_order >= 0", name="ck_positions_sort_order"),
        CheckConstraint(
            "default_scope_type IS NULL OR default_scope_type IN "
            "('self', 'working_venues', 'explicit_venues', 'company')",
            name="ck_positions_default_scope_type",
        ),
        Index(
            "uq_positions_active_company_code",
            "company_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND is_active"),
        ),
        Index("ix_positions_company_active", "company_id", "is_active"),
        Index("ix_positions_default_access_profile_id", "default_access_profile_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_access_profile_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    default_scope_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
