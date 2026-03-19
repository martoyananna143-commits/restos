"""Criterion model for evaluation criteria (formerly Rating)."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.evaluation.category import Category
    from app.infra.database.models.evaluation.criterion_set import CriterionSet
    from app.infra.database.models.evaluation.criterion_value import CriterionValue


class Criterion(Base, TimestampMixin, SoftDeleteMixin):
    """Criterion model - вопросы/критерии оценки (да/нет)."""

    __tablename__ = "criteria"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    value_type: Mapped[str] = mapped_column(String(20), default="boolean", nullable=False)  # 'boolean', 'string', 'number'

    # Relationships
    category: Mapped[Optional["Category"]] = relationship(
        "Category", back_populates="criteria", lazy="joined"
    )

    criterion_values: Mapped[List["CriterionValue"]] = relationship(
        "CriterionValue",
        back_populates="criterion",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    criterion_sets: Mapped[List["CriterionSet"]] = relationship(
        "CriterionSet",
        secondary="criterion_set_criterion",
        back_populates="criteria",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Criterion(id={self.id}, name={self.name}, code={self.code})>"
