"""Organization model for managing business organizations."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

__all__ = ["Organization"]

if TYPE_CHECKING:
    from app.infra.database.models.employee.employee import Employee
    from app.infra.database.models.evaluation.evaluation import Evaluation


class Organization(Base, TimestampMixin, SoftDeleteMixin):
    """Organization model - организация/компания/заведение."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    employees: Mapped[List["Employee"]] = relationship(
        "Employee", back_populates="organization", lazy="selectin"
    )

    evaluations: Mapped[List["Evaluation"]] = relationship(
        "Evaluation", back_populates="organization", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name}, code={self.code})>"
