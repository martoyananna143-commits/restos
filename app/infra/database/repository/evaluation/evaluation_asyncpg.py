"""Evaluation repository implementation using asyncpg and buildpg."""

import orjson
from datetime import datetime
from typing import Any, Awaitable, Dict, List, Optional, Union

from buildpg.asyncpg import BuildPgPool  # type: ignore
from dependency_injector import providers

from app.infra.database.connection.postgresql.connection import (
    _get_connection as get_connection,
)
from app.infra.database.repository.evaluation.dto import (
    CreateEvaluationDTO,
    EvaluationDTO,
    UpdateEvaluationDTO,
)


class EvaluationRepositoryAsyncpg:
    """Repository for Evaluation model using asyncpg and buildpg."""

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

    async def get_by_id(self, evaluation_id: int) -> Optional[EvaluationDTO]:
        """Get evaluation by ID.

        Args:
            evaluation_id: Evaluation ID.

        Returns:
            EvaluationDTO if found, None otherwise.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            row = await conn.fetchrow_b(
                """
                SELECT
                    id, evaluation_type_id, organization_id,
                    filled_by_employee_id, evaluated_employee_id, criterion_set_id,
                    evaluation_date, total_criteria, passed_criteria,
                    failed_criteria, score_percentage, comment, status,
                    meta, created_at, updated_at, deleted_at
                FROM evaluations
                WHERE id = :evaluation_id AND deleted_at IS NULL
                """,
                evaluation_id=evaluation_id,
            )

            if not row:
                return None

            return EvaluationDTO(
                id=row["id"],
                evaluation_type_id=row["evaluation_type_id"],
                organization_id=row["organization_id"],
                filled_by_employee_id=row["filled_by_employee_id"],
                evaluated_employee_id=row["evaluated_employee_id"],
                criterion_set_id=row["criterion_set_id"],
                evaluation_date=row["evaluation_date"],
                total_criteria=row["total_criteria"],
                passed_criteria=row["passed_criteria"],
                failed_criteria=row["failed_criteria"],
                score_percentage=row["score_percentage"],
                comment=row["comment"],
                status=row["status"],
                meta=row["meta"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def create(self, dto: CreateEvaluationDTO) -> EvaluationDTO:
        """Create a new evaluation.

        Args:
            dto: CreateEvaluationDTO with evaluation data.

        Returns:
            Created EvaluationDTO instance.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            evaluation_date = dto.evaluation_date or datetime.utcnow()

            # Сериализуем meta в JSON для JSONB поля
            meta_json = orjson.dumps(dto.meta or {}).decode('utf-8') if dto.meta else '{}'
            
            row = await conn.fetchrow_b(
                """
                INSERT INTO evaluations (
                    evaluation_type_id, organization_id,
                    filled_by_employee_id, evaluated_employee_id, criterion_set_id,
                    evaluation_date, total_criteria, passed_criteria,
                    failed_criteria, score_percentage, comment, status, meta
                )
                VALUES (
                    :evaluation_type_id, :organization_id,
                    :filled_by_employee_id, :evaluated_employee_id, :criterion_set_id,
                    :evaluation_date, :total_criteria, :passed_criteria,
                    :failed_criteria, :score_percentage, :comment, :status, :meta::jsonb
                )
                RETURNING
                    id, evaluation_type_id, organization_id,
                    filled_by_employee_id, evaluated_employee_id, criterion_set_id,
                    evaluation_date, total_criteria, passed_criteria,
                    failed_criteria, score_percentage, comment, status,
                    meta, created_at, updated_at, deleted_at
                """,
                evaluation_type_id=dto.evaluation_type_id,
                organization_id=dto.organization_id,
                filled_by_employee_id=dto.filled_by_employee_id,
                evaluated_employee_id=dto.evaluated_employee_id,
                criterion_set_id=dto.criterion_set_id,
                evaluation_date=evaluation_date,
                total_criteria=dto.total_criteria,
                passed_criteria=dto.passed_criteria,
                failed_criteria=dto.failed_criteria,
                score_percentage=dto.score_percentage,
                comment=dto.comment,
                status=dto.status,
                meta=meta_json,
            )

            return EvaluationDTO(
                id=row["id"],
                evaluation_type_id=row["evaluation_type_id"],
                organization_id=row["organization_id"],
                filled_by_employee_id=row["filled_by_employee_id"],
                evaluated_employee_id=row["evaluated_employee_id"],
                criterion_set_id=row["criterion_set_id"],
                evaluation_date=row["evaluation_date"],
                total_criteria=row["total_criteria"],
                passed_criteria=row["passed_criteria"],
                failed_criteria=row["failed_criteria"],
                score_percentage=row["score_percentage"],
                comment=row["comment"],
                status=row["status"],
                meta=row["meta"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def update(
        self, evaluation_id: int, dto: UpdateEvaluationDTO
    ) -> Optional[EvaluationDTO]:
        """Update evaluation data.

        Args:
            evaluation_id: Evaluation ID to update.
            dto: UpdateEvaluationDTO with fields to update.

        Returns:
            Updated EvaluationDTO instance or None if not found.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            # Build update query dynamically based on provided fields
            updates = []
            params: Dict[str, Any] = {"evaluation_id": evaluation_id}

            if dto.evaluation_type_id is not None:
                updates.append("evaluation_type_id = :evaluation_type_id")
                params["evaluation_type_id"] = dto.evaluation_type_id
            if dto.organization_id is not None:
                updates.append("organization_id = :organization_id")
                params["organization_id"] = dto.organization_id
            if dto.filled_by_employee_id is not None:
                updates.append("filled_by_employee_id = :filled_by_employee_id")
                params["filled_by_employee_id"] = dto.filled_by_employee_id
            if dto.evaluated_employee_id is not None:
                updates.append("evaluated_employee_id = :evaluated_employee_id")
                params["evaluated_employee_id"] = dto.evaluated_employee_id
            if dto.criterion_set_id is not None:
                updates.append("criterion_set_id = :criterion_set_id")
                params["criterion_set_id"] = dto.criterion_set_id
            if dto.evaluation_date is not None:
                updates.append("evaluation_date = :evaluation_date")
                params["evaluation_date"] = dto.evaluation_date
            if dto.total_criteria is not None:
                updates.append("total_criteria = :total_criteria")
                params["total_criteria"] = dto.total_criteria
            if dto.passed_criteria is not None:
                updates.append("passed_criteria = :passed_criteria")
                params["passed_criteria"] = dto.passed_criteria
            if dto.failed_criteria is not None:
                updates.append("failed_criteria = :failed_criteria")
                params["failed_criteria"] = dto.failed_criteria
            if dto.score_percentage is not None:
                updates.append("score_percentage = :score_percentage")
                params["score_percentage"] = dto.score_percentage
            if dto.comment is not None:
                updates.append("comment = :comment")
                params["comment"] = dto.comment
            if dto.status is not None:
                updates.append("status = :status")
                params["status"] = dto.status
            if dto.meta is not None:
                updates.append("meta = :meta::jsonb")
                # Сериализуем meta в JSON для JSONB поля
                params["meta"] = orjson.dumps(dto.meta).decode('utf-8')

            if not updates:
                # No updates to make, just return the existing record
                return await self.get_by_id(evaluation_id)

            updates.append("updated_at = NOW()")

            query = f"""
                UPDATE evaluations
                SET {', '.join(updates)}
                WHERE id = :evaluation_id AND deleted_at IS NULL
                RETURNING
                    id, evaluation_type_id, organization_id,
                    filled_by_employee_id, evaluated_employee_id, criterion_set_id,
                    evaluation_date, total_criteria, passed_criteria,
                    failed_criteria, score_percentage, comment, status,
                    meta, created_at, updated_at, deleted_at
            """

            row = await conn.fetchrow_b(query, **params)

            if not row:
                return None

            return EvaluationDTO(
                id=row["id"],
                evaluation_type_id=row["evaluation_type_id"],
                organization_id=row["organization_id"],
                filled_by_employee_id=row["filled_by_employee_id"],
                evaluated_employee_id=row["evaluated_employee_id"],
                criterion_set_id=row["criterion_set_id"],
                evaluation_date=row["evaluation_date"],
                total_criteria=row["total_criteria"],
                passed_criteria=row["passed_criteria"],
                failed_criteria=row["failed_criteria"],
                score_percentage=row["score_percentage"],
                comment=row["comment"],
                status=row["status"],
                meta=row["meta"] or {},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                deleted_at=row["deleted_at"],
            )

    async def get_analytics_data(
        self,
        organization_id: int,
        criterion_ids: Optional[List[int]] = None,
        employee_ids: Optional[List[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        evaluation_type_id: Optional[int] = None,
    ) -> List[Dict]:
        """Get evaluation data for analytics with filters.

        Args:
            organization_id: Organization ID.
            criterion_ids: Optional list of criterion IDs to filter.
            employee_ids: Optional list of employee IDs to filter.
            date_from: Optional start date.
            date_to: Optional end date.
            evaluation_type_id: Optional evaluation type ID.

        Returns:
            List of dictionaries with evaluation data including criterion values.
        """
        pool = await self._get_pool()
        async with get_connection(pool) as conn:
            # Базовый запрос с JOIN для получения значений критериев
            query = """
                SELECT
                    e.id, e.evaluation_type_id, e.organization_id,
                    e.filled_by_employee_id, e.evaluated_employee_id,
                    e.criterion_set_id, e.evaluation_date,
                    e.total_criteria, e.passed_criteria, e.failed_criteria,
                    e.score_percentage, e.comment, e.status,
                    cv.criterion_id, cv.value, cv.value_json, cv.notes as cv_notes,
                    c.value_type as criterion_value_type
                FROM evaluations e
                LEFT JOIN criterion_values cv ON e.id = cv.evaluation_id
                LEFT JOIN criteria c ON cv.criterion_id = c.id
                WHERE e.organization_id = :organization_id
                    AND e.deleted_at IS NULL
            """
            params: Dict[str, Any] = {"organization_id": organization_id}

            # Добавляем фильтры
            if date_from:
                query += " AND e.evaluation_date >= :date_from"
                params["date_from"] = date_from
            if date_to:
                query += " AND e.evaluation_date <= :date_to"
                params["date_to"] = date_to
            if evaluation_type_id:
                query += " AND e.evaluation_type_id = :evaluation_type_id"
                params["evaluation_type_id"] = evaluation_type_id
            if employee_ids:
                query += " AND (e.evaluated_employee_id = ANY(:employee_ids) OR e.filled_by_employee_id = ANY(:employee_ids))"
                params["employee_ids"] = employee_ids

            query += " ORDER BY e.evaluation_date DESC, e.id DESC"

            rows = await conn.fetch_b(query, **params)

            # Группируем данные по evaluation_id
            evaluations_dict: Dict[int, Dict] = {}
            for row in rows:
                eval_id = row["id"]
                if eval_id not in evaluations_dict:
                    evaluations_dict[eval_id] = {
                        "id": eval_id,
                        "evaluation_type_id": row["evaluation_type_id"],
                        "organization_id": row["organization_id"],
                        "filled_by_employee_id": row["filled_by_employee_id"],
                        "evaluated_employee_id": row["evaluated_employee_id"],
                        "criterion_set_id": row["criterion_set_id"],
                        "evaluation_date": row["evaluation_date"],
                        "total_criteria": row["total_criteria"],
                        "passed_criteria": row["passed_criteria"],
                        "failed_criteria": row["failed_criteria"],
                        "score_percentage": row["score_percentage"],
                        "comment": row["comment"],
                        "status": row["status"],
                        "criterion_values": [],
                    }

                # Добавляем значение критерия, если есть
                if row["criterion_id"]:
                    criterion_id = row["criterion_id"]
                    # Фильтруем по criterion_ids, если указаны
                    if not criterion_ids or criterion_id in criterion_ids:
                        # Извлекаем значение
                        value = None
                        # Используем value_type из таблицы criteria, если доступен, иначе из value_json
                        value_type = row.get("criterion_value_type") or "boolean"
                        if row.get("value_json"):
                            value_data = row["value_json"]
                            
                            # Если value_json приходит как строка JSON, парсим её
                            if isinstance(value_data, str):
                                try:
                                    value_data = orjson.loads(value_data)
                                except (orjson.JSONDecodeError, TypeError, ValueError):
                                    # Если не удалось распарсить, используем как есть
                                    value_data = value_data
                            
                            if isinstance(value_data, dict):
                                value = value_data.get("value")
                                # Используем тип из criteria, если не указан в value_json
                                if not value_type or value_type == "boolean":
                                    value_type = value_data.get("type", value_type or "boolean")
                                
                                # Для числовых типов убеждаемся, что значение правильно извлечено
                                if value_type == "number" and value is not None:
                                    # Если значение в JSON уже число, оставляем как есть
                                    # Если строка, пытаемся преобразовать
                                    if isinstance(value, str):
                                        try:
                                            # Пробуем преобразовать строку в число
                                            cleaned = value.strip()
                                            if cleaned:
                                                if "." in cleaned or "e" in cleaned.lower() or "E" in cleaned:
                                                    value = float(cleaned)
                                                else:
                                                    value = int(cleaned)
                                            else:
                                                value = None
                                        except (ValueError, TypeError):
                                            # Если не удалось преобразовать, оставляем None
                                            value = None
                                    # Если уже число (int/float), оставляем как есть
                                    elif isinstance(value, (int, float)):
                                        value = float(value) if isinstance(value, float) or not isinstance(value, int) else int(value)
                            else:
                                # Если value_json не dict после парсинга, используем как есть
                                value = value_data
                        else:
                            # Если value_json нет, используем старое поле value (для обратной совместимости)
                            value = row["value"]

                        evaluations_dict[eval_id]["criterion_values"].append({
                            "criterion_id": criterion_id,
                            "value": value,
                            "value_type": value_type or "boolean",
                            "notes": row["cv_notes"],
                        })

            return list(evaluations_dict.values())
