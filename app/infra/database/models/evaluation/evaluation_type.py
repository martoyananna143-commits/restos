"""EvaluationType model for evaluation categorization."""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.evaluation.criterion import Criterion
    from app.infra.database.models.evaluation.evaluation import Evaluation


class EvaluationType(Base, TimestampMixin, SoftDeleteMixin):
    """Evaluation type model (КЛН, evaluation forms, etc)."""

    __tablename__ = "evaluation_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Relationships
    evaluations: Mapped[List["Evaluation"]] = relationship(
        "Evaluation", back_populates="evaluation_type", lazy="selectin"
    )

    criteria: Mapped[List["Criterion"]] = relationship(
        "Criterion", back_populates="evaluation_type", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<EvaluationType(id={self.id}, name={self.name}, code={self.code})>"
