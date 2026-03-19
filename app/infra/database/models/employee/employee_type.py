"""EmployeeType model for employee type management."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.employee.employee import Employee


class EmployeeType(Base, TimestampMixin):
    """Employee type model for categorizing employees."""

    __tablename__ = "employee_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_administrator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    employees: Mapped[List["Employee"]] = relationship(
        "Employee", back_populates="employee_type", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<EmployeeType(id={self.id}, name={self.name}, code={self.code})>"
