"""EvaluationType model for evaluation categorization."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.evaluation.evaluation import Evaluation
    from app.infra.database.models.organization.organization import Organization


class EvaluationType(Base, TimestampMixin, SoftDeleteMixin):
    """Evaluation type model (КЛН, evaluation forms, etc).
    
    Each evaluation type belongs to a specific organization.
    """

    __tablename__ = "evaluation_types"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_evaluation_types_org_name"),
        UniqueConstraint("organization_id", "code", name="uq_evaluation_types_org_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    organization: Mapped[Optional["Organization"]] = relationship(
        "Organization", back_populates="evaluation_types", lazy="selectin"
    )
    evaluations: Mapped[List["Evaluation"]] = relationship(
        "Evaluation", back_populates="evaluation_type", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<EvaluationType(id={self.id}, name={self.name}, org_id={self.organization_id})>"
