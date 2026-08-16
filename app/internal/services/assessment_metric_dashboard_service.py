"""Aggregate-only restaurant metric dashboard service."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models import (
    AssessmentAttempt,
    AssessmentMetricDefinition,
    AssessmentMetricObservation,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateVersion,
    Company,
    Venue,
)
from app.internal.services.access_decision_service import AccessDecisionService


READ_PERMISSION = "assessment.assignment.read"
MANAGE_PERMISSION = "assessment.assignment.manage"
_HUNDRED = Decimal("100")
_SCORE_QUANTUM = Decimal("0.0001")
_COVERAGE_QUANTUM = Decimal("0.000001")


class AssessmentMetricDashboardPermissionDenied(Exception):
    pass


class AssessmentMetricDashboardInvalid(Exception):
    pass


class AssessmentMetricDashboardService:
    """Read metric components without exposing attempts, answers, or PII."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def template_options(
        self,
        account_id: UUID,
        company_id: UUID,
        now: datetime,
        *,
        venue_id: UUID | None,
    ) -> list[dict[str, Any]]:
        checked_now = self._aware(now, "now")
        venue_scope = await self._require_read_scope(
            account_id, company_id, venue_id, checked_now
        )
        statement = (
            select(
                AssessmentTemplateVersion.id,
                AssessmentTemplate.name,
                AssessmentTemplate.activity_type,
                func.count(func.distinct(AssessmentAttempt.id)),
            )
            .join(
                AssessmentAttempt,
                AssessmentAttempt.template_version_id == AssessmentTemplateVersion.id,
            )
            .join(
                AssessmentMetricObservation,
                AssessmentMetricObservation.attempt_id == AssessmentAttempt.id,
            )
            .join(
                AssessmentTemplate,
                AssessmentTemplate.id == AssessmentTemplateVersion.template_id,
            )
            .where(
                AssessmentMetricObservation.company_id == company_id,
                AssessmentMetricObservation.scoring_algorithm == "weighted_v1",
                AssessmentMetricObservation.scoring_version == 1,
                AssessmentAttempt.status == "submitted",
            )
            .group_by(
                AssessmentTemplateVersion.id,
                AssessmentTemplate.name,
                AssessmentTemplate.activity_type,
            )
            .order_by(AssessmentTemplate.name, AssessmentTemplateVersion.id)
        )
        if venue_id is not None:
            statement = statement.where(
                AssessmentMetricObservation.venue_id == venue_id
            )
        elif venue_scope is not None:
            statement = statement.where(
                AssessmentMetricObservation.venue_id.in_(venue_scope)
            )
        return [
            {
                "template_version_id": version_id,
                "name": name,
                "activity_type": activity_type,
                "completed_observation_count": count,
            }
            for version_id, name, activity_type, count in (
                await self._session.execute(statement)
            ).all()
        ]

    async def dashboard(
        self,
        account_id: UUID,
        company_id: UUID,
        now: datetime,
        *,
        venue_id: UUID | None,
        source_type: str | None,
        section_code: str | None,
        from_at: datetime | None,
        to_at: datetime | None,
        period: str | None = None,
        compare_previous: bool = False,
    ) -> dict[str, Any]:
        checked_now = self._aware(now, "now")
        venue_scope = await self._require_read_scope(
            account_id, company_id, venue_id, checked_now
        )
        timezone_name = await self._timezone_name(company_id, venue_id)
        if period is not None:
            checked_from, checked_to, previous_from, previous_to = self._period_bounds(
                checked_now, timezone_name, period
            )
            compare_previous = period == "today" and compare_previous
        else:
            checked_to = self._aware(to_at, "to_at") if to_at else checked_now
            checked_from = (
                self._aware(from_at, "from_at")
                if from_at
                else checked_to - timedelta(days=30)
            )
            previous_to = checked_from
            previous_from = checked_from - (checked_to - checked_from)
        empty_today = period == "today" and checked_from == checked_to
        if (
            checked_from > checked_to
            or (checked_from == checked_to and not empty_today)
            or checked_to > checked_now
            or checked_to - checked_from > timedelta(days=366)
        ):
            raise AssessmentMetricDashboardInvalid("invalid observation period")

        definitions = (
            (
                await self._session.execute(
                    select(AssessmentMetricDefinition)
                    .where(AssessmentMetricDefinition.status == "active")
                    .order_by(AssessmentMetricDefinition.code)
                )
            )
            .scalars()
            .all()
        )

        aggregate_columns = (
            AssessmentMetricObservation.metric_definition_id,
            AssessmentMetricObservation.source_type,
            AssessmentMetricObservation.scoring_algorithm,
            AssessmentMetricObservation.scoring_version,
            func.sum(AssessmentMetricObservation.numerator),
            func.sum(AssessmentMetricObservation.denominator),
            func.sum(
                AssessmentMetricObservation.coverage
                * AssessmentMetricObservation.denominator
            ),
            func.sum(AssessmentMetricObservation.critical_failure_count),
            func.sum(AssessmentMetricObservation.stop_factor_count),
            func.count(AssessmentMetricObservation.id),
            func.max(AssessmentMetricObservation.observed_at),
        )

        def aggregate_statement(start: datetime, end: datetime):
            statement = select(*aggregate_columns).where(
                AssessmentMetricObservation.company_id == company_id,
                AssessmentMetricObservation.observed_at >= start,
                AssessmentMetricObservation.observed_at < end,
            )
            statement = statement.group_by(
                AssessmentMetricObservation.metric_definition_id,
                AssessmentMetricObservation.source_type,
                AssessmentMetricObservation.scoring_algorithm,
                AssessmentMetricObservation.scoring_version,
            ).order_by(
                AssessmentMetricObservation.metric_definition_id,
                AssessmentMetricObservation.source_type,
            )
            if venue_id is not None:
                statement = statement.where(
                    AssessmentMetricObservation.venue_id == venue_id
                )
            elif venue_scope is not None:
                statement = statement.where(
                    AssessmentMetricObservation.venue_id.in_(venue_scope)
                )
            if source_type is not None:
                statement = statement.where(
                    AssessmentMetricObservation.source_type == source_type
                )
            return statement

        statement = aggregate_statement(checked_from, checked_to)
        previous_scores: dict[tuple[UUID, str, str, int], Decimal] = {}
        if compare_previous and section_code is None:
            for (
                metric_id,
                previous_source,
                previous_algorithm,
                previous_version,
                numerator,
                denominator,
                *_,
            ) in (
                await self._session.execute(
                    aggregate_statement(previous_from, previous_to)
                )
            ).all():
                checked_denominator = Decimal(denominator)
                if checked_denominator > 0:
                    previous_scores[
                        (
                            metric_id,
                            previous_source,
                            previous_algorithm,
                            previous_version,
                        )
                    ] = (
                        Decimal(numerator) / checked_denominator * _HUNDRED
                    ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
        elif compare_previous:
            previous_scores = await self._section_scores(
                company_id,
                venue_id=venue_id,
                venue_scope=venue_scope,
                source_type=source_type,
                section_code=section_code,
                start=previous_from,
                end=previous_to,
            )

        grouped: dict[UUID, list[dict[str, Any]]] = {}
        rows = (
            await self._section_rows(
                company_id,
                venue_id=venue_id,
                venue_scope=venue_scope,
                source_type=source_type,
                section_code=section_code,
                start=checked_from,
                end=checked_to,
            )
            if section_code is not None
            else (await self._session.execute(statement)).all()
        )
        current_component_sets: dict[UUID, set[tuple[str, str, int]]] = {}
        previous_component_sets: dict[UUID, set[tuple[str, str, int]]] = {}
        for metric_id, source, algorithm, version in previous_scores:
            previous_component_sets.setdefault(metric_id, set()).add(
                (source, algorithm, version)
            )
        for metric_id, source, algorithm, version, *_ in rows:
            current_component_sets.setdefault(metric_id, set()).add(
                (source, algorithm, version)
            )
        for (
            metric_id,
            row_source_type,
            scoring_algorithm,
            scoring_version,
            numerator,
            denominator,
            coverage_numerator,
            critical_failures,
            stop_factors,
            observations,
            latest_at,
        ) in rows:
            checked_denominator = Decimal(denominator)
            if checked_denominator <= 0:
                raise AssessmentMetricDashboardInvalid(
                    "invalid metric observation denominator"
                )
            score = (Decimal(numerator) / checked_denominator * _HUNDRED).quantize(
                _SCORE_QUANTUM, rounding=ROUND_HALF_UP
            )
            coverage = (Decimal(coverage_numerator) / checked_denominator).quantize(
                _COVERAGE_QUANTUM, rounding=ROUND_HALF_UP
            )
            comparison_key = (
                metric_id,
                row_source_type,
                scoring_algorithm,
                scoring_version,
            )
            component_sets_match = (
                current_component_sets.get(metric_id, set())
                == previous_component_sets.get(metric_id, set())
            )
            if not compare_previous:
                comparison_status = "not_requested"
                delta = None
            elif not previous_component_sets.get(metric_id):
                comparison_status = "no_previous_data"
                delta = None
            elif not component_sets_match:
                comparison_status = "not_comparable"
                delta = None
            elif comparison_key in previous_scores:
                comparison_status = "comparable"
                delta = format(score - previous_scores[comparison_key], "f")
            else:
                comparison_status = "not_comparable"
                delta = None
            grouped.setdefault(metric_id, []).append(
                {
                    "source_type": row_source_type,
                    "scoring_algorithm": scoring_algorithm,
                    "scoring_version": scoring_version,
                    "score_percent": format(score, "f"),
                    "coverage": format(coverage, "f"),
                    "observation_count": int(observations),
                    "critical_failure_count": int(critical_failures or 0),
                    "stop_factor_count": int(stop_factors or 0),
                    "latest_at": latest_at,
                    "comparison_status": comparison_status,
                    "delta": delta,
                    "delta_unit": "percentage_points" if delta is not None else None,
                }
            )

        return {
            "company_id": company_id,
            "venue_id": venue_id,
            "source_type": source_type,
            "section_code": section_code,
            "from_at": checked_from,
            "to_at": checked_to,
            "timezone": timezone_name,
            "comparison_from_at": previous_from if compare_previous else None,
            "comparison_to_at": previous_to if compare_previous else None,
            "aggregation_status": "components_only",
            "metrics": [
                {
                    "code": definition.code,
                    "title": definition.title,
                    "composite_score_percent": None,
                    "target_score_percent": None,
                    "overdue_action_count": None,
                    "status": (
                        "components_available"
                        if grouped.get(definition.id)
                        else "no_data"
                    ),
                    "components": grouped.get(definition.id, []),
                }
                for definition in definitions
            ],
        }

    async def sources(
        self,
        account_id: UUID,
        company_id: UUID,
        metric_code: str,
        now: datetime,
        *,
        venue_id: UUID | None,
        source_type: str | None,
        section_code: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        checked_now = self._aware(now, "now")
        venue_scope = await self._require_read_scope(
            account_id, company_id, venue_id, checked_now
        )
        statement = (
            select(AssessmentMetricObservation, AssessmentMetricDefinition)
            .join(
                AssessmentMetricDefinition,
                AssessmentMetricDefinition.id
                == AssessmentMetricObservation.metric_definition_id,
            )
            .where(
                AssessmentMetricObservation.company_id == company_id,
                AssessmentMetricDefinition.code == metric_code,
                AssessmentMetricDefinition.status == "active",
            )
            .order_by(
                AssessmentMetricObservation.observed_at.desc(),
                AssessmentMetricObservation.id,
            )
        )
        if venue_id is not None:
            statement = statement.where(
                AssessmentMetricObservation.venue_id == venue_id
            )
        elif venue_scope is not None:
            statement = statement.where(
                AssessmentMetricObservation.venue_id.in_(venue_scope)
            )
        if source_type is not None:
            statement = statement.where(
                AssessmentMetricObservation.source_type == source_type
            )
        statement = statement.limit(1000 if section_code is not None else limit)
        rows = (await self._session.execute(statement)).all()
        if section_code is not None:
            rows = [
                row
                for row in rows
                if any(
                    item.get("section_code") == section_code
                    for item in row[0].detail_json.get("items", [])
                )
            ][:limit]
        return [
            {
                "observation_id": observation.id,
                "attempt_id": observation.attempt_id,
                "product_measurement_id": observation.product_measurement_id,
                "source_type": observation.source_type,
                "scoring_algorithm": observation.scoring_algorithm,
                "scoring_version": observation.scoring_version,
                "score_percent": format(observation.score_percent, "f"),
                "coverage": format(observation.coverage, "f"),
                "critical_failure_count": observation.critical_failure_count,
                "stop_factor_count": observation.stop_factor_count,
                "observed_at": observation.observed_at,
                "items": [
                    item
                    for item in observation.detail_json.get("items", [])
                    if section_code is None or item.get("section_code") == section_code
                ],
            }
            for observation, _ in rows
        ]

    async def low_indicators(
        self,
        account_id: UUID,
        company_id: UUID,
        template_version_id: UUID,
        now: datetime,
        *,
        venue_id: UUID | None,
        from_at: datetime | None,
        to_at: datetime | None,
    ) -> dict[str, Any]:
        checked_now = self._aware(now, "now")
        checked_to = self._aware(to_at, "to_at") if to_at else checked_now
        checked_from = (
            self._aware(from_at, "from_at")
            if from_at
            else checked_to - timedelta(days=30)
        )
        if checked_from >= checked_to or checked_to - checked_from > timedelta(days=366):
            raise AssessmentMetricDashboardInvalid("invalid ranking period")
        venue_scope = await self._require_read_scope(
            account_id, company_id, venue_id, checked_now
        )
        statement = (
            select(AssessmentMetricObservation)
            .join(
                AssessmentAttempt,
                AssessmentAttempt.id == AssessmentMetricObservation.attempt_id,
            )
            .where(
                AssessmentMetricObservation.company_id == company_id,
                AssessmentMetricObservation.scoring_algorithm == "weighted_v1",
                AssessmentMetricObservation.scoring_version == 1,
                AssessmentMetricObservation.observed_at >= checked_from,
                AssessmentMetricObservation.observed_at < checked_to,
                AssessmentAttempt.template_version_id == template_version_id,
                AssessmentAttempt.status == "submitted",
            )
            .order_by(
                AssessmentMetricObservation.attempt_id,
                AssessmentMetricObservation.metric_definition_id,
            )
        )
        if venue_id is not None:
            statement = statement.where(AssessmentMetricObservation.venue_id == venue_id)
        elif venue_scope is not None:
            statement = statement.where(
                AssessmentMetricObservation.venue_id.in_(venue_scope)
            )
        observations = (await self._session.execute(statement)).scalars().all()
        attempt_ids = {value.attempt_id for value in observations if value.attempt_id}
        item_values: dict[UUID, dict[UUID, dict[str, Any]]] = {}
        for observation in observations:
            if observation.attempt_id is None:
                continue
            for contribution in observation.detail_json.get("items", []):
                source_normalized = contribution.get("source_normalized")
                if source_normalized is None:
                    continue
                try:
                    item_id = UUID(str(contribution["item_id"]))
                    score = Decimal(str(source_normalized))
                except (KeyError, ValueError, TypeError) as error:
                    raise AssessmentMetricDashboardInvalid(
                        "invalid ranking contribution"
                    ) from error
                if not score.is_finite() or score < 0 or score > 1:
                    raise AssessmentMetricDashboardInvalid(
                        "invalid ranking contribution"
                    )
                per_attempt = item_values.setdefault(item_id, {})
                existing = per_attempt.get(observation.attempt_id)
                candidate = {
                    "score": score,
                    "critical": contribution.get("critical_failure") is True,
                    "stop_factor": contribution.get("stop_factor_failure") is True,
                }
                if existing is not None and existing != candidate:
                    raise AssessmentMetricDashboardInvalid(
                        "ambiguous ranking contribution"
                    )
                per_attempt[observation.attempt_id] = candidate
        item_ids = list(item_values)
        labels = {
            item.id: (item.code, item.prompt)
            for item in (
                (
                    await self._session.execute(
                        select(AssessmentTemplateItem).where(
                            AssessmentTemplateItem.template_version_id
                            == template_version_id,
                            AssessmentTemplateItem.id.in_(item_ids),
                        )
                    )
                )
                .scalars()
                .all()
                if item_ids
                else []
            )
        }
        ranked = self._rank_low_indicators(
            item_values,
            labels,
            observation_count=len(attempt_ids),
        )
        return {
            "template_version_id": template_version_id,
            "scoring_algorithm": "weighted_v1",
            "scoring_version": 1,
            "from_at": checked_from,
            "to_at": checked_to,
            "minimum_observations": 3,
            "maximum_items": 10,
            "observation_count": len(attempt_ids),
            "status": "available" if ranked else "insufficient_data",
            "items": ranked[:10],
        }

    @staticmethod
    def _rank_low_indicators(
        values: dict[UUID, dict[UUID, dict[str, Any]]],
        labels: dict[UUID, tuple[str, str]],
        *,
        observation_count: int,
    ) -> list[dict[str, Any]]:
        if observation_count <= 0:
            return []
        candidates = []
        for item_id, per_attempt in values.items():
            if len(per_attempt) < 3 or item_id not in labels:
                continue
            score = (
                sum((value["score"] for value in per_attempt.values()), Decimal("0"))
                / Decimal(len(per_attempt))
                * _HUNDRED
            ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
            code, label = labels[item_id]
            candidates.append(
                {
                    "item_code": code,
                    "label": label,
                    "score_percent": format(score, "f"),
                    "sample_count": len(per_attempt),
                    "coverage": format(
                        (Decimal(len(per_attempt)) / Decimal(observation_count)).quantize(
                            _COVERAGE_QUANTUM, rounding=ROUND_HALF_UP
                        ),
                        "f",
                    ),
                    "critical_failure_count": sum(
                        value["critical"] for value in per_attempt.values()
                    ),
                    "stop_factor_count": sum(
                        value["stop_factor"] for value in per_attempt.values()
                    ),
                    "_score": score,
                }
            )
        candidates.sort(key=lambda value: (value["_score"], value["item_code"]))
        previous_score: Decimal | None = None
        current_rank = 0
        for position, value in enumerate(candidates, start=1):
            if value["_score"] != previous_score:
                current_rank = position
                previous_score = value["_score"]
            value["rank"] = current_rank
            value.pop("_score")
        return candidates

    async def _section_scores(
        self,
        company_id: UUID,
        *,
        venue_id: UUID | None,
        venue_scope: set[UUID] | None,
        source_type: str | None,
        section_code: str,
        start: datetime,
        end: datetime,
    ) -> dict[tuple[UUID, str, str, int], Decimal]:
        return {
            (metric_id, row_source, algorithm, version): (
                Decimal(numerator) / Decimal(denominator) * _HUNDRED
            ).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)
            for metric_id, row_source, algorithm, version, numerator, denominator, *_ in (
                await self._section_rows(
                    company_id,
                    venue_id=venue_id,
                    venue_scope=venue_scope,
                    source_type=source_type,
                    section_code=section_code,
                    start=start,
                    end=end,
                )
            )
        }

    async def _section_rows(
        self,
        company_id: UUID,
        *,
        venue_id: UUID | None,
        venue_scope: set[UUID] | None,
        source_type: str | None,
        section_code: str,
        start: datetime,
        end: datetime,
    ) -> list[tuple[Any, ...]]:
        """Rebuild a section component only from immutable item contributions."""

        statement = select(AssessmentMetricObservation).where(
            AssessmentMetricObservation.company_id == company_id,
            AssessmentMetricObservation.observed_at >= start,
            AssessmentMetricObservation.observed_at < end,
        )
        if venue_id is not None:
            statement = statement.where(
                AssessmentMetricObservation.venue_id == venue_id
            )
        elif venue_scope is not None:
            statement = statement.where(
                AssessmentMetricObservation.venue_id.in_(venue_scope)
            )
        if source_type is not None:
            statement = statement.where(
                AssessmentMetricObservation.source_type == source_type
            )
        observations = (await self._session.execute(statement)).scalars().all()
        grouped: dict[tuple[UUID, str, str, int], dict[str, Any]] = {}
        for observation in observations:
            items = [
                item
                for item in observation.detail_json.get("items", [])
                if item.get("section_code") == section_code
            ]
            if not items:
                continue
            key = (
                observation.metric_definition_id,
                observation.source_type,
                observation.scoring_algorithm,
                observation.scoring_version,
            )
            value = grouped.setdefault(
                key,
                {
                    "numerator": Decimal("0"),
                    "denominator": Decimal("0"),
                    "total_weight": Decimal("0"),
                    "critical": 0,
                    "stop_factor": 0,
                    "count": 0,
                    "latest": observation.observed_at,
                },
            )
            value["count"] += 1
            value["latest"] = max(value["latest"], observation.observed_at)
            for item in items:
                weight = Decimal(str(item["weight"]))
                value["total_weight"] += weight
                if item.get("normalized") is None:
                    continue
                normalized = Decimal(str(item["normalized"]))
                value["numerator"] += normalized * weight
                value["denominator"] += weight
                value["critical"] += int(item.get("critical_failure") is True)
                value["stop_factor"] += int(item.get("stop_factor_failure") is True)
        rows = []
        for (metric_id, row_source, algorithm, version), value in sorted(
            grouped.items(), key=lambda pair: tuple(map(str, pair[0]))
        ):
            if value["denominator"] <= 0 or value["total_weight"] <= 0:
                continue
            rows.append(
                (
                    metric_id,
                    row_source,
                    algorithm,
                    version,
                    value["numerator"],
                    value["denominator"],
                    (
                        value["denominator"]
                        / value["total_weight"]
                        * value["denominator"]
                    ),
                    value["critical"],
                    value["stop_factor"],
                    value["count"],
                    value["latest"],
                )
            )
        return rows

    async def _require_read_scope(
        self,
        account_id: UUID,
        company_id: UUID,
        venue_id: UUID | None,
        now: datetime,
    ) -> set[UUID] | None:
        access = AccessDecisionService(self._session)
        if (
            await access.can_in_company(account_id, company_id, READ_PERMISSION, now)
            or await access.can_in_company(
                account_id, company_id, MANAGE_PERMISSION, now
            )
        ):
            if venue_id is not None and not await access.can_for_venue(
                account_id, company_id, READ_PERMISSION, venue_id, now
            ) and not await access.can_for_venue(
                account_id, company_id, MANAGE_PERMISSION, venue_id, now
            ):
                raise AssessmentMetricDashboardPermissionDenied("permission denied")
            return None
        accessible = await access.list_accessible_venue_ids(
            account_id, company_id, READ_PERMISSION, now
        )
        accessible.update(
            await access.list_accessible_venue_ids(
                account_id, company_id, MANAGE_PERMISSION, now
            )
        )
        if not accessible or (venue_id is not None and venue_id not in accessible):
            raise AssessmentMetricDashboardPermissionDenied("permission denied")
        return accessible

    async def _timezone_name(
        self, company_id: UUID, venue_id: UUID | None
    ) -> str:
        company_timezone = (
            await self._session.execute(
                select(Company.timezone).where(
                    Company.id == company_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if company_timezone is None:
            raise AssessmentMetricDashboardPermissionDenied("permission denied")
        if venue_id is None:
            return company_timezone
        venue_timezone = (
            await self._session.execute(
                select(Venue.timezone).where(
                    Venue.id == venue_id,
                    Venue.company_id == company_id,
                    Venue.status != "closed",
                    Venue.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return venue_timezone or company_timezone

    @staticmethod
    def _period_bounds(
        now: datetime, timezone_name: str, period: str
    ) -> tuple[datetime, datetime, datetime, datetime]:
        if period != "today":
            raise AssessmentMetricDashboardInvalid("unsupported metric period")
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise AssessmentMetricDashboardInvalid("invalid metric timezone") from error
        local_now = now.astimezone(local_timezone)
        today = local_now.date()
        previous_day = today - timedelta(days=1)
        current_from = datetime.combine(today, time.min, local_timezone)
        start_of_next_day = datetime.combine(
            today + timedelta(days=1), time.min, local_timezone
        )
        current_to = min(start_of_next_day, local_now)
        previous_from = datetime.combine(previous_day, time.min, local_timezone)
        previous_to = datetime.combine(
            previous_day,
            local_now.timetz().replace(tzinfo=None),
            local_timezone,
        )
        return tuple(
            value.astimezone(timezone.utc)
            for value in (current_from, current_to, previous_from, previous_to)
        )

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AssessmentMetricDashboardInvalid(f"{name} must be timezone-aware")
        return value.astimezone(timezone.utc)
