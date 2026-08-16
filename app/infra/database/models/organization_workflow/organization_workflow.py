"""Tenant-bound reusable invitations, tasks, events, and media references."""

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
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, TimestampMixin


class GroupInvitation(Base, TimestampMixin):
    __tablename__ = "group_invitations"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_group_invitations_id_company"),
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_group_invitations_venue_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["position_id", "company_id"],
            ["positions.id", "positions.company_id"],
            name="fk_group_invitations_position_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["access_profile_id", "company_id"],
            ["access_profiles.id", "access_profiles.company_id"],
            name="fk_group_invitations_access_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('active','revoked','expired')",
            name="ck_group_invitations_status",
        ),
        CheckConstraint(
            "octet_length(token_digest) = 32", name="ck_group_invitations_digest"
        ),
        CheckConstraint(
            "max_registrations BETWEEN 1 AND 200", name="ck_group_invitations_capacity"
        ),
        CheckConstraint(
            "registration_count BETWEEN 0 AND max_registrations",
            name="ck_group_invitations_count",
        ),
        CheckConstraint("expires_at > created_at", name="ck_group_invitations_expiry"),
        CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by_account_id IS NOT NULL) OR "
            "(status <> 'revoked' AND revoked_at IS NULL AND revoked_by_account_id IS NULL)",
            name="ck_group_invitations_revoke_state",
        ),
        Index(
            "uq_group_invitations_active_digest",
            "token_digest",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        UniqueConstraint(
            "company_id", "request_id", name="uq_group_invitations_company_request"
        ),
        Index("ix_group_invitations_company_status", "company_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    access_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    created_by_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    token_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    max_registrations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )
    registration_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by_account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )


class GroupInvitationRegistration(Base, TimestampMixin):
    __tablename__ = "group_invitation_registrations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_invitation_id", "company_id"],
            ["group_invitations.id", "group_invitations.company_id"],
            name="fk_group_registrations_invitation_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_group_registrations_profile_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending_activation','active','rejected')",
            name="ck_group_registrations_status",
        ),
        CheckConstraint(
            "(status = 'active' AND activated_at IS NOT NULL AND activated_by_account_id IS NOT NULL) OR "
            "(status <> 'active' AND activated_at IS NULL AND activated_by_account_id IS NULL)",
            name="ck_group_registrations_activation_state",
        ),
        UniqueConstraint(
            "group_invitation_id", "request_id", name="uq_group_registrations_request"
        ),
        Index(
            "uq_group_registrations_company_account",
            "company_id",
            "account_id",
            unique=True,
            postgresql_where=text("account_id IS NOT NULL AND status <> 'rejected'"),
        ),
        Index("ix_group_registrations_company_status", "company_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    group_invitation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    employee_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending_activation",
        server_default="pending_activation",
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activated_by_account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "company_id", name="uq_tasks_id_company"),
        UniqueConstraint(
            "author_account_id", "request_id", name="uq_tasks_author_request"
        ),
        ForeignKeyConstraint(
            ["venue_id", "company_id"],
            ["venues.id", "venues.company_id"],
            name="fk_tasks_venue_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('draft','assigned','completed','cancelled')",
            name="ck_tasks_status",
        ),
        CheckConstraint("version >= 1", name="ck_tasks_version"),
        Index("ix_tasks_company_status", "company_id", "status"),
        Index("ix_tasks_attempt", "assessment_attempt_id"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    venue_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    assessment_attempt_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("assessment_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    author_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TaskAssignment(Base, TimestampMixin):
    __tablename__ = "task_assignments"
    __table_args__ = (
        UniqueConstraint(
            "id", "task_id", "company_id", name="uq_task_assignments_id_task_company"
        ),
        ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["tasks.id", "tasks.company_id"],
            name="fk_task_assignments_task_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["employee_profile_id", "company_id"],
            ["employee_profiles.id", "employee_profiles.company_id"],
            name="fk_task_assignments_profile_company",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('assigned','submitted_for_review','changes_requested','accepted')",
            name="ck_task_assignments_status",
        ),
        CheckConstraint("version >= 1", name="ck_task_assignments_version"),
        UniqueConstraint(
            "task_id", "employee_profile_id", name="uq_task_assignments_task_employee"
        ),
        Index("ix_task_assignments_employee_status", "employee_profile_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    employee_profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="assigned", server_default="assigned"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by_account_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=True,
    )


class TaskPhoto(Base, TimestampMixin):
    __tablename__ = "task_photos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["tasks.id", "tasks.company_id"],
            name="fk_task_photos_task_company",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_assignment_id", "task_id", "company_id"],
            [
                "task_assignments.id",
                "task_assignments.task_id",
                "task_assignments.company_id",
            ],
            name="fk_task_photos_assignment_task_company",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "media_status IN ('pending','ready','deleting','deleted')",
            name="ck_task_photos_status",
        ),
        CheckConstraint(
            "mime_type IN ('image/jpeg','image/png')", name="ck_task_photos_mime"
        ),
        CheckConstraint("byte_size BETWEEN 1 AND 10485760", name="ck_task_photos_size"),
        CheckConstraint(
            "octet_length(sha256_digest) = 32", name="ck_task_photos_digest"
        ),
        UniqueConstraint("object_key", name="uq_task_photos_object_key"),
        Index("ix_task_photos_task_status", "task_id", "media_status"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_assignment_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    uploaded_by_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["tasks.id", "tasks.company_id"],
            name="fk_task_events_task_company",
            ondelete="CASCADE",
        ),
        Index("ix_task_events_task_created", "task_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    safe_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
