"""Company-specific access profile models."""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class AccessProfile(Base, TimestampMixin, SoftDeleteMixin):
    """Technical permission template scoped to one company."""

    __tablename__ = "access_profiles"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_access_profiles_id_company"),
        CheckConstraint(
            "code = lower(code) AND code ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_access_profiles_code_slug",
        ),
        CheckConstraint(
            "maximum_scope IN ('self', 'working_venues', 'explicit_venues', 'company')",
            name="ck_access_profiles_maximum_scope",
        ),
        CheckConstraint("version >= 1", name="ck_access_profiles_version"),
        Index(
            "uq_access_profiles_active_company_code",
            "company_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND is_active"),
        ),
        Index("ix_access_profiles_company_active", "company_id", "is_active"),
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
    maximum_scope: Mapped[str] = mapped_column(String(30), nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )


class AccessProfilePermission(Base):
    """Allow-only permission assigned to an access profile."""

    __tablename__ = "access_profile_permissions"
    __table_args__ = (
        CheckConstraint(
            "permission_code = lower(permission_code) "
            "AND permission_code ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*){1,2}$'",
            name="ck_access_profile_permissions_code",
        ),
        Index("ix_access_profile_permissions_code", "permission_code"),
    )

    access_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("access_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_code: Mapped[str] = mapped_column(String(150), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
