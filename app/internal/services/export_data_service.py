"""Export Data Service for preparing data for export reports."""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from app.infra.database.repository.criterion_value.criterion_value_asyncpg import (
    CriterionValueRepositoryAsyncpg,
)

logger = logging.getLogger(__name__)


class ExportDataService:
    """Service for preparing data for export operations."""

    def __init__(
        self,
        criterion_value_repository: CriterionValueRepositoryAsyncpg,
    ):
        """Initialize export data service.

        Args:
            criterion_value_repository: Criterion value repository instance.
        """
        self.criterion_value_repository = criterion_value_repository

    def _normalize_criterion_value(
        self, value: any, value_type: str
    ) -> any:
        """Normalize criterion value based on its type.

        Args:
            value: Raw value from database.
            value_type: Type of criterion value ('boolean', 'number', 'string').

        Returns:
            Normalized value.
        """
        # If value is a string that looks like JSON, try to parse it
        if isinstance(value, str):
            value_stripped = value.strip()
            if value_stripped.startswith("{") and value_stripped.endswith("}"):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict) and "value" in parsed:
                        # Extract value from JSON object {"type": "...", "value": ...}
                        extracted_value = parsed.get("value")
                        if extracted_value is not None:
                            # Transform type based on type in JSON
                            value_type_from_json = parsed.get("type")
                            if value_type_from_json == "boolean":
                                value = (
                                    bool(extracted_value)
                                    if not isinstance(extracted_value, bool)
                                    else extracted_value
                                )
                            elif value_type_from_json == "number":
                                if isinstance(extracted_value, str):
                                    try:
                                        value = (
                                            float(extracted_value)
                                            if "." in extracted_value
                                            else int(extracted_value)
                                        )
                                    except (ValueError, TypeError):
                                        value = extracted_value
                                else:
                                    value = extracted_value
                            elif value_type_from_json == "string":
                                value = str(extracted_value)
                            else:
                                value = extracted_value
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

        # Normalize boolean values
        if value_type == "boolean":
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "да")
            elif isinstance(value, (int, float)):
                return bool(value)
            else:
                return False

        return value

    async def prepare_evaluation_data_for_export(
        self,
        evaluation_id: int,
        criterion_service,
        criterion_set_service,
        employee_service,
        evaluation_type_service,
    ) -> Dict:
        """Prepare evaluation data for export.

        Args:
            evaluation_id: Evaluation ID.
            criterion_service: Criterion service instance.
            criterion_set_service: Criterion set service instance.
            employee_service: Employee service instance.
            evaluation_type_service: Evaluation type service instance.

        Returns:
            Dictionary with prepared evaluation data.
        """
        # Get criterion values
        criterion_values = await self.criterion_value_repository.get_by_evaluation_id(
            evaluation_id
        )

        # Get criteria
        criterion_ids = [cv.criterion_id for cv in criterion_values]
        criteria_list = []
        boolean_criteria_count = 0
        passed_criteria = 0

        if criterion_ids:
            criteria = await criterion_service.get_by_ids(criterion_ids)
            criteria_map = {crit.id: crit for crit in criteria}

            # Form list of criteria with their values
            for cv in criterion_values:
                criterion = criteria_map.get(cv.criterion_id)
                if not criterion:
                    continue

                # Normalize value
                value = self._normalize_criterion_value(
                    cv.value, criterion.value_type
                )

                if criterion.value_type == "boolean":
                    boolean_criteria_count += 1
                    if value:
                        passed_criteria += 1

                criteria_list.append(
                    {
                        "name": criterion.name,
                        "value": value,
                        "value_type": criterion.value_type,
                        "comment": cv.notes or "",
                    }
                )

            total_criteria = len(criteria_list)
            failed_criteria = boolean_criteria_count - passed_criteria
            score_percentage = (
                (passed_criteria / boolean_criteria_count * 100)
                if boolean_criteria_count > 0
                else 0.0
            )
        else:
            total_criteria = 0
            failed_criteria = 0
            score_percentage = 0.0
            boolean_criteria_count = 0

        return {
            "criteria": criteria_list,
            "total_criteria": total_criteria,
            "passed_criteria": passed_criteria,
            "failed_criteria": failed_criteria,
            "score_percentage": score_percentage,
            "boolean_criteria_count": boolean_criteria_count,
        }

    async def prepare_employee_statistics(
        self,
        employee_id: int,
        organization_id: int,
        analytics_service,
    ) -> Dict:
        """Prepare employee statistics for export.

        Args:
            employee_id: Employee ID.
            organization_id: Organization ID.
            analytics_service: Analytics service instance.

        Returns:
            Dictionary with employee statistics.
        """
        # Get evaluation statistics
        evaluations_data = (
            await analytics_service.evaluation_repository.get_analytics_data(
                organization_id=organization_id,
                criterion_ids=None,
                employee_ids=[employee_id],
                date_from=None,
                date_to=None,
                evaluation_type_id=None,
            )
        )

        seen_ids = set()
        eval_count = 0
        scores = []
        last_eval_date = None

        for eval_data in evaluations_data:
            eval_id = eval_data.get("id")
            if eval_id and eval_id not in seen_ids:
                seen_ids.add(eval_id)
                eval_count += 1
                score = eval_data.get("score_percentage", 0.0)
                if score is not None:
                    scores.append(score)
                eval_date = eval_data.get("evaluation_date")
                if eval_date and (
                    not last_eval_date or eval_date > last_eval_date
                ):
                    last_eval_date = eval_date

        avg_score = sum(scores) / len(scores) if scores else None
        best_score = max(scores) if scores else None
        worst_score = min(scores) if scores else None

        return {
            "total_evaluations": eval_count,
            "avg_score": avg_score,
            "best_score": best_score,
            "worst_score": worst_score,
            "last_evaluation_date": (
                last_eval_date.strftime("%Y-%m-%d %H:%M")
                if last_eval_date
                else None
            ),
        }

    async def prepare_criterion_statistics(
        self,
        criterion_id: int,
        organization_id: int,
        analytics_service,
        criterion_set_service,
    ) -> Dict:
        """Prepare criterion statistics for export.

        Args:
            criterion_id: Criterion ID.
            organization_id: Organization ID.
            analytics_service: Analytics service instance.
            criterion_set_service: Criterion set service instance.

        Returns:
            Dictionary with criterion statistics.
        """
        # Get usage statistics
        evaluations_data = (
            await analytics_service.evaluation_repository.get_analytics_data(
                organization_id=organization_id,
                criterion_ids=[criterion_id],
            )
        )

        seen_eval_ids = set()
        usage_count = 0

        for eval_data in evaluations_data:
            eval_id = eval_data.get("id")
            if eval_id and eval_id not in seen_eval_ids:
                seen_eval_ids.add(eval_id)
                usage_count += 1

        # Get criterion sets that use this criterion
        all_criterion_sets = await criterion_set_service.get_by_organization_id(
            organization_id
        )
        sets_with_criterion = []

        for cs in all_criterion_sets:
            cs_full = await criterion_set_service.get_by_id(cs.id)
            if (
                cs_full
                and hasattr(cs_full, "criterion_ids")
                and cs_full.criterion_ids
                and criterion_id in cs_full.criterion_ids
            ):
                sets_with_criterion.append(cs.name)

        return {
            "usage_count": usage_count,
            "criterion_sets": sets_with_criterion,
        }

    async def prepare_criterion_set_statistics(
        self,
        criterion_set_id: int,
        organization_id: int,
        analytics_service,
    ) -> Dict:
        """Prepare criterion set statistics for export.

        Args:
            criterion_set_id: Criterion set ID.
            organization_id: Organization ID.
            analytics_service: Analytics service instance.

        Returns:
            Dictionary with criterion set statistics.
        """
        # Get usage statistics
        evaluations_data = (
            await analytics_service.evaluation_repository.get_analytics_data(
                organization_id=organization_id,
            )
        )

        seen_eval_ids = set()
        usage_count = 0

        for eval_data in evaluations_data:
            eval_id = eval_data.get("id")
            eval_criterion_set_id = eval_data.get("criterion_set_id")
            if (
                eval_id
                and eval_id not in seen_eval_ids
                and eval_criterion_set_id == criterion_set_id
            ):
                seen_eval_ids.add(eval_id)
                usage_count += 1

        return {
            "usage_count": usage_count,
        }

