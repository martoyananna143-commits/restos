"""CriterionValue repository implementation using asyncpg and buildpg."""

from typing import Any, Awaitable, List, Optional, Union

from buildpg.asyncpg import BuildPgPool
from dependency_injector import providers

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.criterion_value.dto import (
    CreateCriterionValueDTO,
    CriterionValueDTO,
    UpdateCriterionValueDTO,
)
import json


class CriterionValueRepositoryAsyncpg:
    """Repository for CriterionValue model using asyncpg and buildpg."""

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

    async def get_by_evaluation_id(
        self, evaluation_id: int
    ) -> List[CriterionValueDTO]:
        """Get all criterion values by evaluation ID.

        Args:
            evaluation_id: Evaluation ID.

        Returns:
            List of CriterionValueDTO instances.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            rows = await conn.fetch_b(
                """
                SELECT
                    id, evaluation_id, criterion_id, value, value_json, notes,
                    created_at, updated_at
                FROM criterion_values
                WHERE evaluation_id = :evaluation_id
                ORDER BY created_at ASC
                """,
                evaluation_id=evaluation_id,
            )

            result = []
            for row in rows:
                # Поддержка старого формата (value) и нового (value_json)
                if row.get("value_json"):
                    value_data = row["value_json"]
                    if isinstance(value_data, str):
                        try:
                            value_data = json.loads(value_data)
                        except (TypeError, ValueError):
                            value_data = {}
                    if isinstance(value_data, dict):
                        value = value_data.get("value") or value_data.get("Value")
                        # Преобразуем тип в зависимости от типа в JSON; None не превращаем в False
                        if value_data.get("type") == "boolean" and value is not None:
                            value = bool(value)
                        elif value_data.get("type") == "number" and value is not None:
                            value = float(value) if "." in str(value) else int(value)
                        elif value_data.get("type") == "string" and value is not None:
                            value = str(value)
                    else:
                        value = value_data
                else:
                    # Обратная совместимость со старым форматом
                    value = row["value"]
                
                result.append(CriterionValueDTO(
                    id=row["id"],
                    evaluation_id=row["evaluation_id"],
                    criterion_id=row["criterion_id"],
                    value=value,
                    notes=row["notes"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                ))
            return result

    async def get_by_id(self, criterion_value_id: int) -> Optional[CriterionValueDTO]:
        """Get criterion value by ID.

        Args:
            criterion_value_id: CriterionValue ID.

        Returns:
            CriterionValueDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, evaluation_id, criterion_id, value, value_json, notes,
                    created_at, updated_at
                FROM criterion_values
                WHERE id = :criterion_value_id
                """,
                criterion_value_id=criterion_value_id,
            )

            if not row:
                return None

            # Поддержка старого формата (value) и нового (value_json)
            if row.get("value_json"):
                value_data = row["value_json"]
                if isinstance(value_data, str):
                    try:
                        value_data = json.loads(value_data)
                    except (TypeError, ValueError):
                        value_data = {}
                if isinstance(value_data, dict):
                    value = value_data.get("value") or value_data.get("Value")
                    if value_data.get("type") == "boolean" and value is not None:
                        value = bool(value)
                    elif value_data.get("type") == "number" and value is not None:
                        value = float(value) if "." in str(value) else int(value)
                    elif value_data.get("type") == "string" and value is not None:
                        value = str(value)
                else:
                    value = value_data
            else:
                value = row["value"]

            return CriterionValueDTO(
                id=row["id"],
                evaluation_id=row["evaluation_id"],
                criterion_id=row["criterion_id"],
                value=value,
                notes=row["notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def create(self, dto: CreateCriterionValueDTO) -> CriterionValueDTO:
        """Create a new criterion value.

        Args:
            dto: CreateCriterionValueDTO with criterion value data.

        Returns:
            Created CriterionValueDTO instance.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            # Определяем тип значения и создаем JSONB объект
            value_type = "boolean"
            if isinstance(dto.value, bool):
                value_type = "boolean"
            elif isinstance(dto.value, (int, float)):
                value_type = "number"
            elif isinstance(dto.value, str):
                value_type = "string"
            
            value_json = json.dumps({"type": value_type, "value": dto.value})
            
            # Поддержка старого формата для обратной совместимости
            value_bool = dto.value if isinstance(dto.value, bool) else None
            
            row = await conn.fetchrow_b(
                """
                INSERT INTO criterion_values (
                    evaluation_id, criterion_id, value, value_json, notes
                )
                VALUES (
                    :evaluation_id, :criterion_id, :value, :value_json::jsonb, :notes
                )
                ON CONFLICT (evaluation_id, criterion_id)
                DO UPDATE SET
                    value = EXCLUDED.value,
                    value_json = EXCLUDED.value_json,
                    notes = EXCLUDED.notes,
                    updated_at = NOW()
                RETURNING
                    id, evaluation_id, criterion_id, value, value_json, notes,
                    created_at, updated_at
                """,
                evaluation_id=dto.evaluation_id,
                criterion_id=dto.criterion_id,
                value=value_bool,
                value_json=value_json,
                notes=dto.notes,
            )

            # Извлекаем значение из JSONB
            value_data = row["value_json"]
            if isinstance(value_data, dict):
                value = value_data.get("value")
                if value_data.get("type") == "boolean":
                    value = bool(value)
                elif value_data.get("type") == "number":
                    value = float(value) if "." in str(value) else int(value)
                elif value_data.get("type") == "string":
                    value = str(value)
            else:
                value = value_data if value_data is not None else row["value"]

            return CriterionValueDTO(
                id=row["id"],
                evaluation_id=row["evaluation_id"],
                criterion_id=row["criterion_id"],
                value=value,
                notes=row["notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def update(
        self, criterion_value_id: int, dto: UpdateCriterionValueDTO
    ) -> Optional[CriterionValueDTO]:
        """Update criterion value data.

        Args:
            criterion_value_id: CriterionValue ID to update.
            dto: UpdateCriterionValueDTO with fields to update.

        Returns:
            Updated CriterionValueDTO instance or None if not found.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            updates = []
            params = {"criterion_value_id": criterion_value_id}

            if dto.value is not None:
                # Определяем тип значения и создаем JSONB объект
                value_type = "boolean"
                if isinstance(dto.value, bool):
                    value_type = "boolean"
                elif isinstance(dto.value, (int, float)):
                    value_type = "number"
                elif isinstance(dto.value, str):
                    value_type = "string"
                
                value_json = json.dumps({"type": value_type, "value": dto.value})
                updates.append("value_json = :value_json::jsonb")
                params["value_json"] = value_json
                
                # Поддержка старого формата для обратной совместимости
                if isinstance(dto.value, bool):
                    updates.append("value = :value")
                    params["value"] = dto.value
                else:
                    updates.append("value = NULL")
            
            if dto.notes is not None:
                updates.append("notes = :notes")
                params["notes"] = dto.notes

            if not updates:
                return await self.get_by_id(criterion_value_id)

            updates.append("updated_at = NOW()")

            query = f"""
                UPDATE criterion_values
                SET {', '.join(updates)}
                WHERE id = :criterion_value_id
                RETURNING
                    id, evaluation_id, criterion_id, value, value_json, notes,
                    created_at, updated_at
            """

            row = await conn.fetchrow_b(query, **params)

            if not row:
                return None

            # Извлекаем значение из JSONB
            value_data = row["value_json"]
            if isinstance(value_data, dict):
                value = value_data.get("value")
                if value_data.get("type") == "boolean":
                    value = bool(value)
                elif value_data.get("type") == "number":
                    value = float(value) if "." in str(value) else int(value)
                elif value_data.get("type") == "string":
                    value = str(value)
            else:
                value = value_data if value_data is not None else row["value"]

            return CriterionValueDTO(
                id=row["id"],
                evaluation_id=row["evaluation_id"],
                criterion_id=row["criterion_id"],
                value=value,
                notes=row["notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    async def delete_by_evaluation_id(self, evaluation_id: int) -> None:
        """Delete all criterion values for an evaluation.

        Args:
            evaluation_id: Evaluation ID.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            await conn.execute_b(
                """
                DELETE FROM criterion_values
                WHERE evaluation_id = :evaluation_id
                """,
                evaluation_id=evaluation_id,
            )





