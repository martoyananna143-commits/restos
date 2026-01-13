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

    async def get_all(self) -> list[EvaluationTypeDTO]:
        """Get all active evaluation types.

        Returns:
            List of EvaluationTypeDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, name, code, description, is_active, config,
                    created_at, updated_at, deleted_at
                FROM evaluation_types
                WHERE deleted_at IS NULL AND is_active = TRUE
                ORDER BY name ASC
                """
            )

            return [
                EvaluationTypeDTO(
                    id=row["id"],
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
                    id, name, code, description, is_active, config,
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
                    name, code, description, is_active, config
                )
                VALUES (
                    :name, :code, :description, :is_active, :config
                )
                RETURNING
                    id, name, code, description, is_active, config,
                    created_at, updated_at, deleted_at
                """,
                name=dto.name,
                code=dto.code,
                description=dto.description,
                is_active=dto.is_active,
                config=str(dto.config or {}),
            )

            return EvaluationTypeDTO(
                id=row["id"],
                name=row["name"],
                code=row["code"],
                description=row["description"],
                is_active=row["is_active"],
                config=row["config"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

