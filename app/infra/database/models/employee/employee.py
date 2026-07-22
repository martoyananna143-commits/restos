"""Employee model for staff management."""

from datetime import date
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.employee.employee_type import EmployeeType
    from app.infra.database.models.evaluation.evaluation import Evaluation
    from app.infra.database.models.organization.organization import Organization


class Employee(Base, TimestampMixin, SoftDeleteMixin):
    """Employee model for tracking staff members."""

    __tablename__ = "employees"
    __table_args__ = (
        # Составной уникальный ключ: один пользователь может быть сотрудником
        # в разных организациях, но в каждой организации только один раз
        UniqueConstraint("telegram_id", "organization_id", name="uq_employee_telegram_organization"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    employee_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("employee_types.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hire_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    employee_type: Mapped["EmployeeType"] = relationship(
        "EmployeeType", back_populates="employees", lazy="joined"
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        foreign_keys=[organization_id],
        back_populates="employees",
        lazy="joined",
    )

    evaluations_filled: Mapped[List["Evaluation"]] = relationship(
        "Evaluation",
        foreign_keys="Evaluation.filled_by_employee_id",
        back_populates="filled_by_employee",
        lazy="selectin",
    )

    evaluations_evaluated: Mapped[List["Evaluation"]] = relationship(
        "Evaluation",
        foreign_keys="Evaluation.evaluated_employee_id",
        back_populates="evaluated_employee",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Employee(id={self.id}, name={self.full_name}, organization={self.organization.name if self.organization else None})>"
