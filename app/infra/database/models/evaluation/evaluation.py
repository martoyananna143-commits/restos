"""Evaluation model for tracking employee evaluations."""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.employee.employee import Employee
    from app.infra.database.models.evaluation.criterion_set import CriterionSet
    from app.infra.database.models.evaluation.criterion_value import CriterionValue
    from app.infra.database.models.evaluation.evaluation_type import EvaluationType
    from app.infra.database.models.organization.organization import Organization


class Evaluation(Base, TimestampMixin, SoftDeleteMixin):
    """Evaluation model - оценка работника."""

    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "evaluated_employee_id IS NULL OR filled_by_employee_id != evaluated_employee_id",
            name="check_different_employees",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evaluation_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evaluation_types.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    filled_by_employee_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    evaluated_employee_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True
    )
    criterion_set_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("criterion_sets.id", ondelete="SET NULL"), nullable=True
    )
    evaluation_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="NOW()"
    )

    total_criteria: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Всего критериев
    passed_criteria: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Прошедших (Да)
    failed_criteria: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # Проваленных (Нет)
    score_percentage: Mapped[float] = mapped_column(
        default=0.0, nullable=False
    )  # Процент успешных

    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False
    )  # draft, completed, reviewed
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    evaluation_type: Mapped["EvaluationType"] = relationship(
        "EvaluationType",
        foreign_keys=[evaluation_type_id],
        back_populates="evaluations",
        lazy="joined",
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
        back_populates="evaluations",
        lazy="joined",
    )

    filled_by_employee: Mapped["Employee"] = relationship(
        "Employee",
        foreign_keys=[filled_by_employee_id],
        back_populates="evaluations_filled",
        lazy="joined",
    )

    evaluated_employee: Mapped[Optional["Employee"]] = relationship(
        "Employee",
        foreign_keys=[evaluated_employee_id],
        back_populates="evaluations_evaluated",
        lazy="joined",
    )

    criterion_values: Mapped[List["CriterionValue"]] = relationship(
        "CriterionValue",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    criterion_set: Mapped[Optional["CriterionSet"]] = relationship(
        "CriterionSet",
        foreign_keys=[criterion_set_id],
        lazy="joined",
    )

    def __repr__(self) -> str:
        return f"<Evaluation(id={self.id}, organization={self.organization.name if self.organization else None}, score={self.score_percentage:.1f}%)>"
