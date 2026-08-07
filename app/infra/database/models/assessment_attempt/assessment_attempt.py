"""Assigned assessment, draft attempt, and normalized answer models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, TimestampMixin


class AssessmentAssignment(Base, TimestampMixin):
    __tablename__ = "assessment_assignments"
    __table_args__ = (
        CheckConstraint("status IN ('assigned', 'in_progress', 'completed', 'revoked')", name="ck_assessment_assignments_status"),
        CheckConstraint("due_at IS NULL OR due_at > assigned_at", name="ck_assessment_assignments_due_after_assigned"),
        CheckConstraint(
            "((status = 'revoked' AND revoked_at IS NOT NULL AND completed_at IS NULL) OR "
            "(status = 'completed' AND completed_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status IN ('assigned', 'in_progress') AND revoked_at IS NULL AND completed_at IS NULL))",
            name="ck_assessment_assignments_state_timestamps",
        ),
        Index("ix_assessment_assignments_employee_status", "employee_profile_id", "status"),
        Index("ix_assessment_assignments_company_status", "company_id", "status"),
        Index("ix_assessment_assignments_due_at", "due_at"),
        Index(
            "uq_assessment_assignments_active_employee_version",
            "company_id",
            "employee_profile_id",
            "template_version_id",
            unique=True,
            postgresql_where=text("status IN ('assigned', 'in_progress')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    employee_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"), nullable=False)
    template_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assessment_template_versions.id", ondelete="RESTRICT"), nullable=False)
    assigned_by_employee_profile_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="SET NULL"), nullable=True)
    assigned_by_account_id: Mapped[Optional[UUID]] = mapped_column(PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="assigned", server_default="assigned")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentAttempt(Base, TimestampMixin):
    __tablename__ = "assessment_attempts"
    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_assessment_attempts_assignment_id"),
        CheckConstraint("status IN ('draft', 'submitted')", name="ck_assessment_attempts_status"),
        CheckConstraint("revision >= 0", name="ck_assessment_attempts_revision"),
        CheckConstraint(
            "((status = 'draft' AND submitted_at IS NULL AND result_json IS NULL) OR "
            "(status = 'submitted' AND submitted_at IS NOT NULL AND result_json IS NOT NULL))",
            name="ck_assessment_attempts_submission_state",
        ),
        Index("ix_assessment_attempts_account_status", "account_id", "status"),
        Index("ix_assessment_attempts_employee_status", "employee_profile_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assessment_assignments.id", ondelete="RESTRICT"), nullable=False)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False)
    employee_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("employee_profiles.id", ondelete="RESTRICT"), nullable=False)
    template_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assessment_template_versions.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_saved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)


class AssessmentAttemptAnswer(Base, TimestampMixin):
    __tablename__ = "assessment_attempt_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "item_id", name="uq_assessment_attempt_answers_attempt_item"),
        CheckConstraint(
            "answer_type IN ('boolean', 'score', 'integer', 'decimal', 'text', "
            "'single_choice', 'multi_choice', 'date', 'time')",
            name="ck_assessment_attempt_answers_type",
        ),
        Index("ix_assessment_attempt_answers_attempt_id", "attempt_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assessment_attempts.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("assessment_template_items.id", ondelete="RESTRICT"), nullable=False)
    answer_type: Mapped[str] = mapped_column(String(30), nullable=False)
    value_json: Mapped[Any] = mapped_column(JSONB, nullable=False)
