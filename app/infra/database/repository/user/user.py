"""User repository implementation."""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.user import User
from app.infra.database.repository.user.dto import (
    CreateUserDTO,
    UpdateUserDTO,
    UserDTO,
)


class UserRepository:
    """Repository for User model."""

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy async session.
        """
        self.session = session

    async def get_by_telegram_id(
        self, telegram_id: int, chat_id: int
    ) -> Optional[User]:
        """Get user by telegram_id and chat_id.

        Args:
            telegram_id: Telegram user ID.
            chat_id: Chat ID.

        Returns:
            User if found, None otherwise.
        """
        stmt = select(User).where(
            User.telegram_id == telegram_id,
            User.chat_id == chat_id,
            User.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, dto: CreateUserDTO) -> User:
        """Create a new user.

        Args:
            dto: CreateUserDTO with user data.

        Returns:
            Created User instance.
        """
        user = User(
            telegram_id=dto.telegram_id,
            username=dto.username,
            first_name=dto.first_name,
            last_name=dto.last_name,
            chat_id=dto.chat_id,
            is_verified=dto.is_verified,
            is_active=dto.is_active,
            joined_at=dto.joined_at or datetime.utcnow(),
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update(self, user: User, dto: UpdateUserDTO) -> User:
        """Update user data.

        Args:
            user: User instance to update.
            dto: UpdateUserDTO with fields to update.

        Returns:
            Updated User instance.
        """
        if dto.username is not None:
            user.username = dto.username
        if dto.first_name is not None:
            user.first_name = dto.first_name
        if dto.last_name is not None:
            user.last_name = dto.last_name
        if dto.is_verified is not None:
            user.is_verified = dto.is_verified
        if dto.is_active is not None:
            user.is_active = dto.is_active

        await self.session.flush()
        await self.session.refresh(user)
        return user

    def to_dto(self, user: User) -> UserDTO:
        """Convert User model to UserDTO.

        Args:
            user: User model instance.

        Returns:
            UserDTO instance.
        """
        return UserDTO(
            id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            chat_id=user.chat_id,
            is_verified=user.is_verified,
            is_active=user.is_active,
            joined_at=user.joined_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
            deleted_at=user.deleted_at,
        )
