"""User service for business logic."""

from typing import Optional

from app.infra.database.repository.user.dto import (
    CreateUserDTO,
    TelegramUserDTO,
    UpdateUserDTO,
    UserDTO,
)
from app.infra.database.repository.user.user_asyncpg import UserRepositoryAsyncpg


class UserService:
    """Service for user operations."""

    def __init__(self, repository: UserRepositoryAsyncpg):
        """Initialize service with repository.

        Args:
            repository: User repository instance.
        """
        self.repository = repository

    async def get_or_create_user(
        self, telegram_user: TelegramUserDTO, chat_id: int
    ) -> tuple[UserDTO, bool]:
        """Get existing user or create new one.

        Args:
            telegram_user: Telegram user data.
            chat_id: Chat ID.

        Returns:
            Tuple of (UserDTO, created: bool).
        """
        user = await self.repository.get_by_telegram_id(
            telegram_user.telegram_id, chat_id
        )

        if user:
            return user, False

        create_dto = CreateUserDTO(
            telegram_id=telegram_user.telegram_id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            chat_id=chat_id,
            is_verified=False,
            is_active=True,
        )

        new_user = await self.repository.create(create_dto)
        return new_user, True

    async def sync_user_with_telegram(
        self, telegram_user: TelegramUserDTO, chat_id: int
    ) -> Optional[UserDTO]:
        """Sync user data with Telegram data.

        Checks if user exists, compares fields, and updates if needed.

        Args:
            telegram_user: Telegram user data.
            chat_id: Chat ID.

        Returns:
            Updated UserDTO or None if user not found.
        """
        user = await self.repository.get_by_telegram_id(
            telegram_user.telegram_id, chat_id
        )

        if not user:
            return None

        # Check if any fields changed
        needs_update = False
        update_dto = UpdateUserDTO(telegram_id=telegram_user.telegram_id)

        if user.username != telegram_user.username:
            update_dto.username = telegram_user.username
            needs_update = True

        if user.first_name != telegram_user.first_name:
            update_dto.first_name = telegram_user.first_name
            needs_update = True

        if user.last_name != telegram_user.last_name:
            update_dto.last_name = telegram_user.last_name
            needs_update = True

        if needs_update:
            # Increment version if updating
            new_version = (user.version or 0) + 1
            update_dto.version = new_version
            return await self.repository.update(user.id, update_dto)

        return user

