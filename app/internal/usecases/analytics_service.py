"""Analytics Service for evaluation data analysis."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import defaultdict

from app.infra.database.repository.evaluation.evaluation_asyncpg import (
    EvaluationRepositoryAsyncpg,
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for analytics and reporting on evaluation data."""

    def __init__(
        self,
        evaluation_repository: EvaluationRepositoryAsyncpg,
    ):
        """Initialize analytics service.

        Args:
            evaluation_repository: Evaluation repository instance.
        """
        self.evaluation_repository = evaluation_repository

    async def get_criteria_statistics(
        self,
        organization_id: int,
        criterion_ids: Optional[List[int]] = None,
        employee_ids: Optional[List[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        evaluation_type_id: Optional[int] = None,
    ) -> Dict:
        """Get statistics by criteria.

        Args:
            organization_id: Organization ID.
            criterion_ids: Optional list of criterion IDs to filter.
            employee_ids: Optional list of employee IDs to filter.
            date_from: Optional start date.
            date_to: Optional end date.
            evaluation_type_id: Optional evaluation type ID.

        Returns:
            Dictionary with statistics by criteria.
        """
        # Получаем данные из репозитория
        evaluations_data = await self.evaluation_repository.get_analytics_data(
            organization_id=organization_id,
            criterion_ids=criterion_ids,
            employee_ids=employee_ids,
            date_from=date_from,
            date_to=date_to,
            evaluation_type_id=evaluation_type_id,
        )

        # Подсчитываем статистику по критериям
        criterion_stats: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "string_values": [],
            "number_values": [],
        })

        for eval_data in evaluations_data:
            for cv in eval_data.get("criterion_values", []):
                criterion_id = cv["criterion_id"]
                value = cv["value"]
                value_type = cv.get("value_type", "boolean")

                stats = criterion_stats[criterion_id]
                stats["total"] += 1

                if value_type == "boolean":
                    if value is True:
                        stats["passed"] += 1
                    elif value is False:
                        stats["failed"] += 1
                elif value_type == "string" and value is not None:
                    stats["string_values"].append(str(value))
                elif value_type == "number" and value is not None:
                    stats["number_values"].append(float(value))

        # Форматируем результаты
        statistics = []
        for criterion_id, stats in criterion_stats.items():
            stat_entry = {
                "criterion_id": criterion_id,
                "total": stats["total"],
                "passed": stats["passed"],
                "failed": stats["failed"],
            }

            if stats["string_values"]:
                stat_entry["string_values"] = stats["string_values"]
            if stats["number_values"]:
                stat_entry["number_avg"] = sum(stats["number_values"]) / len(stats["number_values"])
                stat_entry["number_min"] = min(stats["number_values"])
                stat_entry["number_max"] = max(stats["number_values"])

            statistics.append(stat_entry)

        return {
            "organization_id": organization_id,
            "criterion_ids": criterion_ids,
            "employee_ids": employee_ids,
            "date_from": date_from,
            "date_to": date_to,
            "evaluation_type_id": evaluation_type_id,
            "total_evaluations": len(evaluations_data),
            "statistics": statistics,
        }

    async def get_average_scores(
        self,
        organization_id: int,
        criterion_ids: Optional[List[int]] = None,
        employee_ids: Optional[List[int]] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        group_by: str = "criterion",  # 'criterion', 'employee', 'date'
    ) -> Dict:
        """Get average scores.

        Args:
            organization_id: Organization ID.
            criterion_ids: Optional list of criterion IDs to filter.
            employee_ids: Optional list of employee IDs to filter.
            date_from: Optional start date.
            date_to: Optional end date.
            group_by: Grouping method ('criterion', 'employee', 'date').

        Returns:
            Dictionary with average scores.
        """
        evaluations_data = await self.evaluation_repository.get_analytics_data(
            organization_id=organization_id,
            criterion_ids=criterion_ids,
            employee_ids=employee_ids,
            date_from=date_from,
            date_to=date_to,
        )

        if group_by == "criterion":
            # Группировка по критериям
            # Разделяем по типам: для number - среднее значение, для boolean - процент прохождения
            criterion_scores: Dict[int, List[float]] = defaultdict(list)
            criterion_types: Dict[int, str] = {}  # Сохраняем тип критерия
            criterion_boolean_stats: Dict[int, Dict[str, int]] = defaultdict(lambda: {"passed": 0, "total": 0})
            
            for eval_data in evaluations_data:
                for cv in eval_data.get("criterion_values", []):
                    criterion_id = cv["criterion_id"]
                    value = cv["value"]
                    value_type = cv.get("value_type") or "boolean"
                    
                    # Нормализуем тип критерия
                    if not value_type or value_type not in ["boolean", "number", "string"]:
                        value_type = "boolean"
                    
                    # Сохраняем тип критерия (берем первый встреченный тип для каждого критерия)
                    if criterion_id not in criterion_types:
                        criterion_types[criterion_id] = value_type

                    if value_type == "boolean":
                        # Для boolean считаем статистику прохождения
                        criterion_boolean_stats[criterion_id]["total"] += 1
                        if value is True:
                            criterion_boolean_stats[criterion_id]["passed"] += 1
                    elif value_type == "number":
                        # Для number сохраняем числовые значения
                        try:
                            if value is not None:
                                num_value = None
                                
                                # Обрабатываем разные типы значений
                                if isinstance(value, (int, float)):
                                    # Уже число - используем как есть
                                    num_value = float(value)
                                elif isinstance(value, str):
                                    # Строка - пытаемся преобразовать в число
                                    # Сначала проверяем, не является ли это JSON-строкой
                                    cleaned = value.strip()
                                    if cleaned:
                                        # Проверяем, не является ли это JSON-объектом
                                        if cleaned.startswith("{") and cleaned.endswith("}"):
                                            try:
                                                parsed = json.loads(cleaned)
                                                if isinstance(parsed, dict):
                                                    # Если это JSON-объект, извлекаем value
                                                    dict_value = parsed.get("value")
                                                    if dict_value is not None:
                                                        if isinstance(dict_value, (int, float)):
                                                            num_value = float(dict_value)
                                                        elif isinstance(dict_value, str):
                                                            # Если value внутри JSON тоже строка, пытаемся преобразовать
                                                            dict_cleaned = dict_value.strip()
                                                            if dict_cleaned:
                                                                num_value = float(dict_cleaned)
                                                            else:
                                                                continue
                                                        else:
                                                            continue
                                                    else:
                                                        continue
                                                else:
                                                    # Если распарсилось не как dict, пытаемся как число
                                                    num_value = float(cleaned)
                                            except (json.JSONDecodeError, ValueError, TypeError):
                                                # Если не JSON, пытаемся как обычное число
                                                try:
                                                    num_value = float(cleaned)
                                                except (ValueError, TypeError):
                                                    continue
                                        else:
                                            # Обычная строка с числом
                                            try:
                                                num_value = float(cleaned)
                                            except (ValueError, TypeError):
                                                continue
                                    else:
                                        continue
                                elif isinstance(value, bool):
                                    # Boolean значение в number критерии - пропускаем
                                    continue
                                elif isinstance(value, dict):
                                    # Если value это dict (из value_json), извлекаем значение
                                    dict_value = value.get("value") if isinstance(value, dict) else value
                                    if dict_value is not None:
                                        if isinstance(dict_value, (int, float)):
                                            num_value = float(dict_value)
                                        elif isinstance(dict_value, str):
                                            cleaned = dict_value.strip()
                                            if cleaned:
                                                num_value = float(cleaned)
                                            else:
                                                continue
                                        else:
                                            continue
                                    else:
                                        continue
                                else:
                                    # Неизвестный тип - пропускаем
                                    continue
                                
                                # Проверяем, что получили валидное число
                                if num_value is not None and not (isinstance(num_value, float) and (num_value != num_value)):  # Проверка на NaN
                                    criterion_scores[criterion_id].append(num_value)
                        except (ValueError, TypeError, AttributeError):
                            # Пропускаем некорректные значения
                            continue

            # Формируем результаты
            averages = []
            for criterion_id in set(list(criterion_scores.keys()) + list(criterion_boolean_stats.keys())):
                value_type = criterion_types.get(criterion_id, "boolean")
                
                if value_type == "number":
                    # Для number критериев - среднее арифметическое значение
                    scores = criterion_scores.get(criterion_id, [])
                    if scores and len(scores) > 0:
                        # Вычисляем среднее арифметическое
                        average_value = sum(scores) / len(scores)
                        averages.append({
                    "criterion_id": criterion_id,
                            "average": average_value,
                    "count": len(scores),
                            "value_type": "number",
                        })
                elif value_type == "boolean":
                    # Для boolean критериев - процент прохождения
                    stats = criterion_boolean_stats.get(criterion_id, {"passed": 0, "total": 0})
                    if stats["total"] > 0:
                        passed_pct = (stats["passed"] / stats["total"]) * 100
                        averages.append({
                            "criterion_id": criterion_id,
                            "average": passed_pct,  # Процент прохождения
                            "count": stats["total"],
                            "value_type": "boolean",
                        })

        elif group_by == "employee":
            # Группировка по сотрудникам
            # Для employee группировки считаем средний score_percentage всех замеров сотрудника
            employee_scores: Dict[int, List[float]] = defaultdict(list)
            for eval_data in evaluations_data:
                employee_id = eval_data.get("evaluated_employee_id")
                if employee_id:
                    score = eval_data.get("score_percentage", 0.0)
                    employee_scores[employee_id].append(score)

            averages = [
                {
                    "employee_id": employee_id,
                    "average": sum(scores) / len(scores) if scores else 0.0,
                    "count": len(scores),
                }
                for employee_id, scores in employee_scores.items()
            ]

        else:  # group_by == "date"
            # Группировка по датам (по дням)
            date_scores: Dict[str, List[float]] = defaultdict(list)
            for eval_data in evaluations_data:
                eval_date = eval_data.get("evaluation_date")
                if eval_date:
                    date_key = eval_date.strftime("%Y-%m-%d")
                    score = eval_data.get("score_percentage", 0.0)
                    date_scores[date_key].append(score)

            averages = [
                {
                    "date": str(date_key),
                    "average": float(sum(scores) / len(scores)) if scores else 0.0,
                    "count": len(scores),
                }
                for date_key, scores in sorted(date_scores.items())
            ]

        return {
            "organization_id": organization_id,
            "group_by": group_by,
            "averages": averages,
        }

    async def get_custom_query(
        self,
        organization_id: int,
        filters: Dict,
    ) -> Dict:
        """Execute custom query with flexible filters.

        Args:
            organization_id: Organization ID.
            filters: Dictionary with filter parameters.

        Returns:
            Dictionary with query results.
        """
        # Извлекаем параметры из filters
        criterion_ids = filters.get("criterion_ids")
        employee_ids = filters.get("employee_ids")
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")
        evaluation_type_id = filters.get("evaluation_type_id")
        min_score = filters.get("min_score")
        max_score = filters.get("max_score")

        # Получаем данные
        evaluations_data = await self.evaluation_repository.get_analytics_data(
            organization_id=organization_id,
            criterion_ids=criterion_ids,
            employee_ids=employee_ids,
            date_from=date_from,
            date_to=date_to,
            evaluation_type_id=evaluation_type_id,
        )

        # Применяем дополнительные фильтры по score
        if min_score is not None or max_score is not None:
            filtered_data = []
            for eval_data in evaluations_data:
                score = eval_data.get("score_percentage", 0.0)
                if min_score is not None and score < min_score:
                    continue
                if max_score is not None and score > max_score:
                    continue
                filtered_data.append(eval_data)
            evaluations_data = filtered_data

        return {
            "organization_id": organization_id,
            "filters": filters,
            "total_results": len(evaluations_data),
            "results": evaluations_data,
        }

