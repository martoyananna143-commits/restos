"""User repository implementation using asyncpg and buildpg."""

from datetime import datetime
from typing import Optional, Union, Awaitable, Any

from buildpg.asyncpg import BuildPgPool
from dependency_injector import providers

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.user.dto import (
    CreateUserDTO,
    UpdateUserDTO,
    UserDTO,
)


class UserRepositoryAsyncpg:
    """Repository for User model using asyncpg and buildpg."""

    def __init__(self, pool: Union[BuildPgPool, Awaitable[BuildPgPool], Any]):
        """Initialize repository with database pool.

        Args:
            pool: PostgreSQL connection pool, awaitable, or Resource provider.
        """
        self._pool = pool
        self._resolved_pool: Optional[BuildPgPool] = None

    async def _get_pool(self) -> BuildPgPool:
        """Get resolved pool, awaiting if necessary.

        Returns:
            Resolved BuildPgPool instance.
        """
        if self._resolved_pool is None:
            # Check if it's already a BuildPgPool
            if isinstance(self._pool, BuildPgPool):
                self._resolved_pool = self._pool
            # Check if it's a Resource provider
            elif isinstance(self._pool, providers.Resource):
                # Resource provider automatically resolves when accessed
                self._resolved_pool = await self._pool()
            # Check if it's a bound method (from postgresql_resource.provided)
            elif hasattr(self._pool, '__self__') and hasattr(self._pool, '__func__'):
                # This is a bound method, we need to get the Resource provider from container
                from app.internal import Container
                container = Container()
                # Get the resource provider and await it
                resource_provider = container.postgresql_resource
                self._resolved_pool = await resource_provider()
            # Check if it's an awaitable (coroutine)
            elif hasattr(self._pool, '__await__'):
                self._resolved_pool = await self._pool
            else:
                raise TypeError(f"Cannot resolve pool: {type(self._pool)}")
        return self._resolved_pool

    async def get_by_telegram_id(
        self, telegram_id: int, chat_id: int
    ) -> Optional[UserDTO]:
        """Get user by telegram_id and chat_id.

        Args:
            telegram_id: Telegram user ID.
            chat_id: Chat ID.

        Returns:
            UserDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            # Use fetchrow_b with named parameters directly
            row = await conn.fetchrow_b(
                """
                SELECT 
                    id, telegram_id, username, first_name, last_name,
                    chat_id, is_verified, is_active, joined_at,
                    created_at, updated_at, deleted_at, version
                FROM users
                WHERE telegram_id = :telegram_id 
                    AND chat_id = :chat_id 
                    AND deleted_at IS NULL
                """,
                telegram_id=telegram_id,
                chat_id=chat_id,
            )

            if not row:
                return None

            return UserDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                chat_id=row["chat_id"],
                is_verified=row["is_verified"],
                is_active=row["is_active"],
                joined_at=row["joined_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
                version=row.get("version", 0),
            )

    async def create(self, dto: CreateUserDTO) -> UserDTO:
        """Create a new user.

        Args:
            dto: CreateUserDTO with user data.

        Returns:
            Created UserDTO instance.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            # Use fetchrow_b with named parameters directly
            row = await conn.fetchrow_b(
                """
                INSERT INTO users (
                    telegram_id, username, first_name, last_name,
                    chat_id, is_verified, is_active, joined_at, version
                )
                VALUES (
                    :telegram_id, :username, :first_name, :last_name,
                    :chat_id, :is_verified, :is_active, :joined_at, :version
                )
                RETURNING 
                    id, telegram_id, username, first_name, last_name,
                    chat_id, is_verified, is_active, joined_at,
                    created_at, updated_at, deleted_at, version
                """,
                telegram_id=dto.telegram_id,
                username=dto.username,
                first_name=dto.first_name,
                last_name=dto.last_name,
                chat_id=dto.chat_id,
                is_verified=dto.is_verified,
                is_active=dto.is_active,
                joined_at=dto.joined_at or datetime.utcnow(),
                version=0,
            )

            return UserDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                chat_id=row["chat_id"],
                is_verified=row["is_verified"],
                is_active=row["is_active"],
                joined_at=row["joined_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
                version=row.get("version", 0),
            )

    async def update(self, user_id: int, dto: UpdateUserDTO) -> Optional[UserDTO]:
        """Update user data.

        Args:
            user_id: User ID to update.
            dto: UpdateUserDTO with fields to update.

        Returns:
            Updated UserDTO instance or None if not found.
        """
        # Check if there are any fields to update
        has_updates = any([
            dto.username is not None,
            dto.first_name is not None,
            dto.last_name is not None,
            dto.is_verified is not None,
            dto.is_active is not None,
            dto.version is not None,
        ])

        if not has_updates:
            return await self.get_by_telegram_id(dto.telegram_id, 0)

        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            # Build SET clause manually for fetchrow_b
            set_parts = []
            if dto.username is not None:
                set_parts.append("username = :username")
            if dto.first_name is not None:
                set_parts.append("first_name = :first_name")
            if dto.last_name is not None:
                set_parts.append("last_name = :last_name")
            if dto.is_verified is not None:
                set_parts.append("is_verified = :is_verified")
            if dto.is_active is not None:
                set_parts.append("is_active = :is_active")
            if dto.version is not None:
                set_parts.append("version = :version")
            set_parts.append("updated_at = NOW()")
            
            set_clause = ", ".join(set_parts)
            
            # Build parameters dict for fetchrow_b
            update_params: dict[str, Any] = {}
            if dto.username is not None:
                update_params["username"] = dto.username
            if dto.first_name is not None:
                update_params["first_name"] = dto.first_name
            if dto.last_name is not None:
                update_params["last_name"] = dto.last_name
            if dto.is_verified is not None:
                update_params["is_verified"] = dto.is_verified
            if dto.is_active is not None:
                update_params["is_active"] = dto.is_active
            if dto.version is not None:
                update_params["version"] = dto.version
            update_params["user_id"] = user_id
            
            # Use fetchrow_b with named parameters directly
            row = await conn.fetchrow_b(
                f"""
                UPDATE users
                SET {set_clause}
                WHERE id = :user_id AND deleted_at IS NULL
                RETURNING 
                    id, telegram_id, username, first_name, last_name,
                    chat_id, is_verified, is_active, joined_at,
                    created_at, updated_at, deleted_at, version
                """,
                **update_params,
            )

            if not row:
                return None

            return UserDTO(
                id=row["id"],
                telegram_id=row["telegram_id"],
                username=row["username"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                chat_id=row["chat_id"],
                is_verified=row["is_verified"],
                is_active=row["is_active"],
                joined_at=row["joined_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
                version=row.get("version", 0),
            )

