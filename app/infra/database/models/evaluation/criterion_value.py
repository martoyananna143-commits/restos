"""CriterionValue model - ответы на критерии в замерах."""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.database.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.infra.database.models.evaluation.criterion import Criterion
    from app.infra.database.models.evaluation.evaluation import Evaluation


class CriterionValue(Base, TimestampMixin):
    """Criterion value - значение критерия в конкретном замере (да/нет)."""

    __tablename__ = "criterion_values"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id", "criterion_id", name="uq_evaluation_criterion"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evaluation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False
    )
    criterion_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("criteria.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[bool] = mapped_column(
        Boolean, nullable=True
    )  # True = Да, False = Нет (для обратной совместимости)
    value_json: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # JSONB для хранения разных типов значений: {"type": "boolean|string|number", "value": ...}
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Доп. примечания

    # Relationships
    evaluation: Mapped["Evaluation"] = relationship(
        "Evaluation",
        foreign_keys=[evaluation_id],
        back_populates="criterion_values",
        lazy="joined",
    )

    criterion: Mapped["Criterion"] = relationship(
        "Criterion", back_populates="criterion_values", lazy="joined"
    )

    def __repr__(self) -> str:
        return f"<CriterionValue(id={self.id}, criterion={self.criterion.name if self.criterion else None}, value={'Да' if self.value else 'Нет'})>"
