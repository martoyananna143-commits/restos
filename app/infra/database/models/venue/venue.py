"""Venue model for the additive architecture."""

from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

__all__ = ["Venue"]


class Venue(Base, TimestampMixin, SoftDeleteMixin):
    """Physical venue; nullable timezone inherits from its company in services."""

    __tablename__ = "venues"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_venues_id_company"),
        CheckConstraint(
            "status IN ('active', 'temporarily_closed', 'closed')",
            name="ck_venues_status",
        ),
        CheckConstraint(
            "code = lower(code) AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_venues_code_slug",
        ),
        UniqueConstraint(
            "legacy_organization_id", name="uq_venues_legacy_organization_id"
        ),
        Index(
            "uq_venues_active_company_code",
            "company_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_venues_company_id", "company_id"),
        Index("ix_venues_legacy_organization_id", "legacy_organization_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    legacy_organization_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    concept: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    timezone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
