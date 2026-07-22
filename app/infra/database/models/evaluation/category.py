"""Category model for grouping criteria."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.evaluation.criterion import Criterion


class Category(Base, TimestampMixin, SoftDeleteMixin):
    """Category model for organizing evaluation criteria."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("code", "parent_id", name="uq_category_code_parent"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    parent: Mapped[Optional["Category"]] = relationship(
        "Category", remote_side="Category.id", back_populates="children", lazy="joined"
    )

    children: Mapped[List["Category"]] = relationship(
        "Category",
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    criteria: Mapped[List["Criterion"]] = relationship(
        "Criterion", back_populates="category", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name={self.name}, code={self.code})>"
