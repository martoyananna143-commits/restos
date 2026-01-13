"""User model for tracking chat members."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin

__all__ = ["User"]


class User(Base, TimestampMixin, SoftDeleteMixin):
    """User model for tracking chat members and their activity."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("telegram_id", "chat_id", name="uq_user_telegram_chat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    joined_at: Mapped[datetime] = mapped_column(nullable=False)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"
