"""EvaluationType repository implementation using asyncpg and buildpg."""

from typing import Any, Awaitable, Optional, Union

from buildpg.asyncpg import BuildPgPool
from dependency_injector import providers

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.evaluation_type.dto import (
    CreateEvaluationTypeDTO,
    EvaluationTypeDTO,
    UpdateEvaluationTypeDTO,
)


class EvaluationTypeRepositoryAsyncpg:
    """Repository for EvaluationType model using asyncpg and buildpg."""

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

    async def get_all(self, organization_id: int | None = None) -> list[EvaluationTypeDTO]:
        """Get all active evaluation types.

        Args:
            organization_id: Optional organization ID to filter by.

        Returns:
            List of EvaluationTypeDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            if organization_id is not None:
                rows = await conn.fetch_b(
                    """
                    SELECT
                        id, organization_id, name, code, description, is_active, config,
                        created_at, updated_at, deleted_at
                    FROM evaluation_types
                    WHERE deleted_at IS NULL AND is_active = TRUE
                        AND organization_id = :organization_id
                    ORDER BY name ASC
                    """,
                    organization_id=organization_id,
                )
            else:
                rows = await conn.fetch_b(
                    """
                    SELECT
                        id, organization_id, name, code, description, is_active, config,
                        created_at, updated_at, deleted_at
                    FROM evaluation_types
                    WHERE deleted_at IS NULL AND is_active = TRUE
                    ORDER BY name ASC
                    """
                )

            return [
                EvaluationTypeDTO(
                    id=row["id"],
                    organization_id=row["organization_id"],
                    name=row["name"],
                    code=row["code"],
                    description=row["description"],
                    is_active=row["is_active"],
                    config=row["config"] or {},
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    deleted_at=row["deleted_at"],
                )
                for row in rows
            ]

    async def get_by_id(self, evaluation_type_id: int) -> Optional[EvaluationTypeDTO]:
        """Get evaluation type by ID.

        Args:
            evaluation_type_id: Evaluation type ID.

        Returns:
            EvaluationTypeDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, organization_id, name, code, description, is_active, config,
                    created_at, updated_at, deleted_at
                FROM evaluation_types
                WHERE id = :evaluation_type_id AND deleted_at IS NULL
                """,
                evaluation_type_id=evaluation_type_id,
            )

            if not row:
                return None

            return EvaluationTypeDTO(
                id=row["id"],
                organization_id=row["organization_id"],
                name=row["name"],
                code=row["code"],
                description=row["description"],
                is_active=row["is_active"],
                config=row["config"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def create(self, dto: CreateEvaluationTypeDTO) -> EvaluationTypeDTO:
        """Create a new evaluation type.

        Args:
            dto: CreateEvaluationTypeDTO with evaluation type data.

        Returns:
            Created EvaluationTypeDTO instance.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                INSERT INTO evaluation_types (
                    organization_id, name, code, description, is_active, config
                )
                VALUES (
                    :organization_id, :name, :code, :description, :is_active, :config
                )
                RETURNING
                    id, organization_id, name, code, description, is_active, config,
                    created_at, updated_at, deleted_at
                """,
                organization_id=dto.organization_id,
                name=dto.name,
                code=dto.code,
                description=dto.description,
                is_active=dto.is_active,
                config=str(dto.config or {}),
            )

            return EvaluationTypeDTO(
                id=row["id"],
                organization_id=row["organization_id"],
                name=row["name"],
                code=row["code"],
                description=row["description"],
                is_active=row["is_active"],
                config=row["config"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def update(
        self, evaluation_type_id: int, dto: UpdateEvaluationTypeDTO
    ) -> Optional[EvaluationTypeDTO]:
        """Update evaluation type."""
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            updates = []
            params = {"evaluation_type_id": evaluation_type_id}
            if dto.name is not None:
                updates.append("name = :name")
                params["name"] = dto.name
            if dto.code is not None:
                updates.append("code = :code")
                params["code"] = dto.code
            if dto.description is not None:
                updates.append("description = :description")
                params["description"] = dto.description
            if dto.is_active is not None:
                updates.append("is_active = :is_active")
                params["is_active"] = dto.is_active
            if dto.config is not None:
                updates.append("config = :config")
                params["config"] = dto.config

            if not updates:
                return await self.get_by_id(evaluation_type_id)

            updates.append("updated_at = NOW()")
            query = f"""
                UPDATE evaluation_types
                SET {", ".join(updates)}
                WHERE id = :evaluation_type_id AND deleted_at IS NULL
                RETURNING
                    id, organization_id, name, code, description, is_active, config,
                    created_at, updated_at, deleted_at
            """
            row = await conn.fetchrow_b(query, **params)
            if not row:
                return None

            return EvaluationTypeDTO(
                id=row["id"],
                organization_id=row["organization_id"],
                name=row["name"],
                code=row["code"],
                description=row["description"],
                is_active=row["is_active"],
                config=row["config"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

