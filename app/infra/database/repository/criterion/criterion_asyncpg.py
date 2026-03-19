"""Criterion repository implementation using asyncpg and buildpg."""

from typing import Any, Awaitable, Optional, Union

from buildpg.asyncpg import BuildPgPool
from dependency_injector import providers

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.criterion.dto import (
    CreateCriterionDTO,
    CriterionDTO,
    UpdateCriterionDTO,
)


class CriterionRepositoryAsyncpg:
    """Repository for Criterion model using asyncpg and buildpg."""

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

    async def get_by_id(self, criterion_id: int) -> Optional[CriterionDTO]:
        """Get criterion by ID.

        Args:
            criterion_id: Criterion ID.

        Returns:
            CriterionDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, organization_id, category_id, name, code,
                    description, sort_order, is_required, is_active, value_type,
                    created_at, updated_at, deleted_at
                FROM criteria
                WHERE id = :criterion_id AND deleted_at IS NULL
                """,
                criterion_id=criterion_id,
            )

            if not row:
                return None

            return CriterionDTO(
                id=row["id"],
                organization_id=row["organization_id"],
                category_id=row["category_id"],
                name=row["name"],
                code=row["code"],
                description=row["description"],
                sort_order=row["sort_order"],
                is_required=row["is_required"],
                is_active=row["is_active"],
                value_type=row.get("value_type", "boolean"),  # По умолчанию boolean для обратной совместимости
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def get_all(self) -> list[CriterionDTO]:
        """Get all criteria across all organizations.

        Returns:
            List of CriterionDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, organization_id, category_id, name, code,
                    description, sort_order, is_required, is_active, value_type,
                    created_at, updated_at, deleted_at
                FROM criteria
                WHERE deleted_at IS NULL
                ORDER BY organization_id ASC, sort_order ASC, name ASC
                """,
            )

            return [
                CriterionDTO(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    category_id=row["category_id"],
                    name=row["name"],
                    code=row["code"],
                    description=row["description"],
                    sort_order=row["sort_order"],
                    is_required=row["is_required"],
                    is_active=row["is_active"],
                    value_type=row.get("value_type", "boolean"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_by_organization_id(
        self, organization_id: int
    ) -> list[CriterionDTO]:
        """Get all criteria by organization ID.

        Args:
            organization_id: Organization ID.

        Returns:
            List of CriterionDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, organization_id, category_id, name, code,
                    description, sort_order, is_required, is_active, value_type,
                    created_at, updated_at, deleted_at
                FROM criteria
                WHERE organization_id = :organization_id
                    AND deleted_at IS NULL
                ORDER BY sort_order ASC, name ASC
                """,
                organization_id=organization_id,
            )

            return [
                CriterionDTO(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    category_id=row["category_id"],
                    name=row["name"],
                    code=row["code"],
                    description=row["description"],
                    sort_order=row["sort_order"],
                    is_required=row["is_required"],
                    is_active=row["is_active"],
                    value_type=row.get("value_type", "boolean"),  # По умолчанию boolean для обратной совместимости
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_by_ids(self, criterion_ids: list[int]) -> list[CriterionDTO]:
        """Get criteria by list of IDs.

        Args:
            criterion_ids: List of criterion IDs.

        Returns:
            List of CriterionDTO instances.
        """
        if not criterion_ids:
            return []

        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, organization_id, category_id, name, code,
                    description, sort_order, is_required, is_active, value_type,
                    created_at, updated_at, deleted_at
                FROM criteria
                WHERE id = ANY(:criterion_ids)
                    AND deleted_at IS NULL
                ORDER BY sort_order ASC, name ASC
                """,
                criterion_ids=criterion_ids,
            )

            return [
                CriterionDTO(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    category_id=row["category_id"],
                    name=row["name"],
                    code=row["code"],
                    description=row["description"],
                    sort_order=row["sort_order"],
                    is_required=row["is_required"],
                    is_active=row["is_active"],
                    value_type=row.get("value_type", "boolean"),  # По умолчанию boolean для обратной совместимости
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def create(self, dto: CreateCriterionDTO) -> CriterionDTO:
        """Create a new criterion.

        Args:
            dto: CreateCriterionDTO with criterion data.

        Returns:
            Created CriterionDTO instance.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                INSERT INTO criteria (
                    organization_id, category_id, name, code,
                    description, sort_order, is_required, is_active, value_type
                )
                VALUES (
                    :organization_id, :category_id, :name, :code,
                    :description, :sort_order, :is_required, :is_active, :value_type
                )
                RETURNING
                    id, organization_id, category_id, name, code,
                    description, sort_order, is_required, is_active, value_type,
                    created_at, updated_at, deleted_at
                """,
                organization_id=dto.organization_id,
                category_id=dto.category_id,
                name=dto.name,
                code=dto.code,
                description=dto.description,
                sort_order=dto.sort_order,
                is_required=dto.is_required,
                is_active=dto.is_active,
                value_type=dto.value_type,
            )

            return CriterionDTO(
                id=row["id"],
                organization_id=row["organization_id"],
                category_id=row["category_id"],
                name=row["name"],
                code=row["code"],
                description=row["description"],
                sort_order=row["sort_order"],
                is_required=row["is_required"],
                is_active=row["is_active"],
                value_type=row.get("value_type", "boolean"),  # По умолчанию boolean для обратной совместимости
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def update(
        self, criterion_id: int, dto: UpdateCriterionDTO
    ) -> Optional[CriterionDTO]:
        """Update criterion data.

        Args:
            criterion_id: Criterion ID to update.
            dto: UpdateCriterionDTO with fields to update.

        Returns:
            Updated CriterionDTO instance or None if not found.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            async with conn.transaction():
                # Проверяем существование критерия
                current = await conn.fetchrow_b(
                    """
                    SELECT id, organization_id
                    FROM criteria
                    WHERE id = :criterion_id AND deleted_at IS NULL
                    """,
                    criterion_id=criterion_id,
                )

                if not current:
                    return None

                # Формируем запрос обновления
                updates = []
                params: dict[str, Any] = {"criterion_id": criterion_id}

                if dto.organization_id is not None:
                    updates.append("organization_id = :organization_id")
                    params["organization_id"] = dto.organization_id
                if dto.category_id is not None:
                    updates.append("category_id = :category_id")
                    params["category_id"] = dto.category_id
                if dto.name is not None:
                    updates.append("name = :name")
                    params["name"] = dto.name
                if dto.code is not None:
                    updates.append("code = :code")
                    params["code"] = dto.code
                if dto.description is not None:
                    updates.append("description = :description")
                    params["description"] = dto.description
                if dto.sort_order is not None:
                    updates.append("sort_order = :sort_order")
                    params["sort_order"] = dto.sort_order
                if dto.is_required is not None:
                    updates.append("is_required = :is_required")
                    params["is_required"] = dto.is_required
                if dto.is_active is not None:
                    updates.append("is_active = :is_active")
                    params["is_active"] = dto.is_active
                if dto.value_type is not None:
                    updates.append("value_type = :value_type")
                    params["value_type"] = dto.value_type

                if not updates:
                    # Если нет обновлений, просто возвращаем текущие данные
                    return await self.get_by_id(criterion_id)

                updates.append("updated_at = NOW()")

                query = f"""
                    UPDATE criteria
                    SET {', '.join(updates)}
                    WHERE id = :criterion_id AND deleted_at IS NULL
                    RETURNING
                        id, organization_id, category_id, name, code,
                        description, sort_order, is_required, is_active, value_type,
                        created_at, updated_at, deleted_at
                """

                row = await conn.fetchrow_b(query, **params)

                if not row:
                    return None

                return CriterionDTO(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    category_id=row["category_id"],
                    name=row["name"],
                    code=row["code"],
                    description=row["description"],
                    sort_order=row["sort_order"],
                    is_required=row["is_required"],
                    is_active=row["is_active"],
                    value_type=row.get("value_type", "boolean"),  # По умолчанию boolean для обратной совместимости
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )

