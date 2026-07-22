"""CriterionSet model for grouping criteria."""

from typing import TYPE_CHECKING, List

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.evaluation.criterion import Criterion

criterion_set_criterion = Table(
    "criterion_set_criterion",
    Base.metadata,
    sa.Column("criterion_set_id", sa.Integer, sa.ForeignKey("criterion_sets.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("criterion_id", sa.Integer, sa.ForeignKey("criteria.id", ondelete="CASCADE"), primary_key=True),
)


class CriterionSet(Base, TimestampMixin, SoftDeleteMixin):
    """CriterionSet model - набор критериев для оценки."""

    __tablename__ = "criterion_sets"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_organization_criterion_set_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(32), default="internal", nullable=False
    )  # internal | google_sheet | google_drive_folder
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    criteria: Mapped[List["Criterion"]] = relationship(
        "Criterion",
        secondary=criterion_set_criterion,
        back_populates="criterion_sets",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<CriterionSet(id={self.id}, name={self.name}, is_default={self.is_default})>"

