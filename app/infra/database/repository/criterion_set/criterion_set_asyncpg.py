"""CriterionSet repository implementation using asyncpg and buildpg."""

from typing import Any, Awaitable, Optional, Union

from buildpg.asyncpg import BuildPgPool
from dependency_injector import providers

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.criterion_set.dto import (
    CreateCriterionSetDTO,
    CriterionSetDTO,
    UpdateCriterionSetDTO,
)


class CriterionSetRepositoryAsyncpg:
    """Repository for CriterionSet model using asyncpg and buildpg."""

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
            if isinstance(self._pool, BuildPgPool):
                self._resolved_pool = self._pool
            elif isinstance(self._pool, providers.Resource):
                self._resolved_pool = await self._pool()
            elif hasattr(self._pool, "__self__") and hasattr(self._pool, "__func__"):
                from app.internal import Container

                container = Container()
                resource_provider = container.postgresql_resource
                self._resolved_pool = await resource_provider()
            elif hasattr(self._pool, "__await__"):
                self._resolved_pool = await self._pool
            else:
                raise TypeError(f"Cannot resolve pool: {type(self._pool)}")
        return self._resolved_pool

    async def get_by_id(self, criterion_set_id: int) -> Optional[CriterionSetDTO]:
        """Get criterion set by ID.

        Args:
            criterion_set_id: CriterionSet ID.

        Returns:
            CriterionSetDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, organization_id, name, description, is_default, is_active,
                    created_at, updated_at, deleted_at
                FROM criterion_sets
                WHERE id = :criterion_set_id AND deleted_at IS NULL
                """,
                criterion_set_id=criterion_set_id,
            )

            if not row:
                return None

            # Получаем IDs критериев в наборе
            criterion_rows = await conn.fetch_b(
                """
                SELECT criterion_id
                FROM criterion_set_criterion
                WHERE criterion_set_id = :criterion_set_id
                """,
                criterion_set_id=criterion_set_id,
            )
            criterion_ids = [r["criterion_id"] for r in criterion_rows] if criterion_rows else []

            return CriterionSetDTO(
                id=row["id"],
                organization_id=row["organization_id"],
                name=row["name"],
                description=row["description"],
                is_default=row["is_default"],
                is_active=row["is_active"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
                criterion_ids=criterion_ids,
            )

    async def get_by_organization_id(
        self, organization_id: int, include_inactive: bool = False
    ) -> list[CriterionSetDTO]:
        """Get all criterion sets by organization ID.

        Args:
            organization_id: Organization ID.
            include_inactive: Include inactive sets.

        Returns:
            List of CriterionSetDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            query = """
                SELECT
                    id, organization_id, name, description, is_default, is_active,
                    created_at, updated_at, deleted_at
                FROM criterion_sets
                WHERE organization_id = :organization_id
                    AND deleted_at IS NULL
            """
            if not include_inactive:
                query += " AND is_active = true"
            query += " ORDER BY is_default DESC, name ASC"

            rows = await conn.fetch_b(query, organization_id=organization_id)

            result = []
            for row in rows:
                # Получаем IDs критериев в наборе
                criterion_rows = await conn.fetch_b(
                    """
                    SELECT criterion_id
                    FROM criterion_set_criterion
                    WHERE criterion_set_id = :criterion_set_id
                    """,
                    criterion_set_id=row["id"],
                )
                criterion_ids = [r["criterion_id"] for r in criterion_rows] if criterion_rows else []

                result.append(
                    CriterionSetDTO(
                        id=row["id"],
                        organization_id=row["organization_id"],
                        name=row["name"],
                        description=row["description"],
                        is_default=row["is_default"],
                        is_active=row["is_active"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                        deleted_at=row["deleted_at"],
                        criterion_ids=criterion_ids,
                    )
                )

            return result

    async def get_default_by_organization_id(
        self, organization_id: int
    ) -> Optional[CriterionSetDTO]:
        """Get default criterion set by organization ID.

        Args:
            organization_id: Organization ID.

        Returns:
            CriterionSetDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, organization_id, name, description, is_default, is_active,
                    created_at, updated_at, deleted_at
                FROM criterion_sets
                WHERE organization_id = :organization_id
                    AND is_default = true
                    AND is_active = true
                    AND deleted_at IS NULL
                LIMIT 1
                """,
                organization_id=organization_id,
            )

            if not row:
                return None

            # Получаем IDs критериев в наборе
            criterion_rows = await conn.fetch_b(
                """
                SELECT criterion_id
                FROM criterion_set_criterion
                WHERE criterion_set_id = :criterion_set_id
                """,
                criterion_set_id=row["id"],
            )
            criterion_ids = [r["criterion_id"] for r in criterion_rows] if criterion_rows else []

            return CriterionSetDTO(
                id=row["id"],
                organization_id=row["organization_id"],
                name=row["name"],
                description=row["description"],
                is_default=row["is_default"],
                is_active=row["is_active"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
                criterion_ids=criterion_ids,
            )

    async def create(self, dto: CreateCriterionSetDTO) -> CriterionSetDTO:
        """Create a new criterion set.

        Args:
            dto: CreateCriterionSetDTO with criterion set data.

        Returns:
            Created CriterionSetDTO instance.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            async with conn.transaction():
                # Если устанавливается is_default=true, сбрасываем другие дефолтные наборы
                if dto.is_default:
                    await conn.execute_b(
                        """
                        UPDATE criterion_sets
                        SET is_default = false
                        WHERE organization_id = :organization_id
                            AND is_default = true
                            AND deleted_at IS NULL
                        """,
                        organization_id=dto.organization_id,
                    )

                # Создаем набор
                row = await conn.fetchrow_b(
                    """
                    INSERT INTO criterion_sets (
                        organization_id, name, description, is_default, is_active
                    )
                    VALUES (
                        :organization_id, :name, :description, :is_default, :is_active
                    )
                    RETURNING
                        id, organization_id, name, description, is_default, is_active,
                        created_at, updated_at, deleted_at
                    """,
                    organization_id=dto.organization_id,
                    name=dto.name,
                    description=dto.description,
                    is_default=dto.is_default,
                    is_active=dto.is_active,
                )

                criterion_set_id = row["id"]

                # Добавляем критерии в набор
                if dto.criterion_ids:
                    for criterion_id in dto.criterion_ids:
                        await conn.execute_b(
                            """
                            INSERT INTO criterion_set_criterion (criterion_set_id, criterion_id)
                            VALUES (:criterion_set_id, :criterion_id)
                            ON CONFLICT DO NOTHING
                            """,
                            criterion_set_id=criterion_set_id,
                            criterion_id=criterion_id,
                        )

                return CriterionSetDTO(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    name=row["name"],
                    description=row["description"],
                    is_default=row["is_default"],
                    is_active=row["is_active"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                    criterion_ids=dto.criterion_ids or [],
                )

    async def update(
        self, criterion_set_id: int, dto: UpdateCriterionSetDTO
    ) -> Optional[CriterionSetDTO]:
        """Update criterion set.

        Args:
            criterion_set_id: CriterionSet ID.
            dto: UpdateCriterionSetDTO with update data.

        Returns:
            Updated CriterionSetDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            async with conn.transaction():
                # Получаем текущий набор для проверки organization_id
                current = await conn.fetchrow_b(
                    """
                    SELECT organization_id, is_default
                    FROM criterion_sets
                    WHERE id = :criterion_set_id AND deleted_at IS NULL
                    """,
                    criterion_set_id=criterion_set_id,
                )

                if not current:
                    return None

                # Если устанавливается is_default=true, сбрасываем другие дефолтные наборы
                if dto.is_default is True:
                    await conn.execute_b(
                        """
                        UPDATE criterion_sets
                        SET is_default = false
                        WHERE organization_id = :organization_id
                            AND id != :criterion_set_id
                            AND is_default = true
                            AND deleted_at IS NULL
                        """,
                        organization_id=current["organization_id"],
                        criterion_set_id=criterion_set_id,
                    )

                # Формируем запрос обновления
                updates = []
                params = {"criterion_set_id": criterion_set_id}

                if dto.name is not None:
                    updates.append("name = :name")
                    params["name"] = dto.name
                if dto.description is not None:
                    updates.append("description = :description")
                    params["description"] = dto.description
                if dto.is_default is not None:
                    updates.append("is_default = :is_default")
                    params["is_default"] = dto.is_default
                if dto.is_active is not None:
                    updates.append("is_active = :is_active")
                    params["is_active"] = dto.is_active

                if updates:
                    updates.append("updated_at = NOW()")
                    query = f"""
                        UPDATE criterion_sets
                        SET {', '.join(updates)}
                        WHERE id = :criterion_set_id
                        RETURNING
                            id, organization_id, name, description, is_default, is_active,
                            created_at, updated_at, deleted_at
                    """
                    row = await conn.fetchrow_b(query, **params)
                else:
                    # Если нет обновлений полей, просто получаем текущие данные
                    row = await conn.fetchrow_b(
                        """
                        SELECT
                            id, organization_id, name, description, is_default, is_active,
                            created_at, updated_at, deleted_at
                        FROM criterion_sets
                        WHERE id = :criterion_set_id
                        """,
                        criterion_set_id=criterion_set_id,
                    )

                # Обновляем критерии в наборе, если указаны
                if dto.criterion_ids is not None:
                    # Удаляем все текущие связи
                    await conn.execute_b(
                        """
                        DELETE FROM criterion_set_criterion
                        WHERE criterion_set_id = :criterion_set_id
                        """,
                        criterion_set_id=criterion_set_id,
                    )

                    # Добавляем новые связи
                    for criterion_id in dto.criterion_ids:
                        await conn.execute_b(
                            """
                            INSERT INTO criterion_set_criterion (criterion_set_id, criterion_id)
                            VALUES (:criterion_set_id, :criterion_id)
                            """,
                            criterion_set_id=criterion_set_id,
                            criterion_id=criterion_id,
                        )

                # Получаем актуальные IDs критериев
                criterion_rows = await conn.fetch_b(
                    """
                    SELECT criterion_id
                    FROM criterion_set_criterion
                    WHERE criterion_set_id = :criterion_set_id
                    """,
                    criterion_set_id=criterion_set_id,
                )
                criterion_ids = [r["criterion_id"] for r in criterion_rows] if criterion_rows else []

                return CriterionSetDTO(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    name=row["name"],
                    description=row["description"],
                    is_default=row["is_default"],
                    is_active=row["is_active"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                    criterion_ids=criterion_ids,
                )

    async def delete(self, criterion_set_id: int) -> bool:
        """Soft delete criterion set.

        Args:
            criterion_set_id: CriterionSet ID.

        Returns:
            True if deleted, False otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            result = await conn.execute_b(
                """
                UPDATE criterion_sets
                SET deleted_at = NOW()
                WHERE id = :criterion_set_id AND deleted_at IS NULL
                """,
                criterion_set_id=criterion_set_id,
            )

            # execute_b returns a string like "UPDATE 1" or "UPDATE 0"
            return result and "UPDATE 1" in str(result)

