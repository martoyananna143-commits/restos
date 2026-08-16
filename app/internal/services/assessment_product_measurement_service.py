"""Repeatable dish/drink taste and speed measurement service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models import (
    AssessmentMetricDefinition,
    AssessmentMetricObservation,
    AssessmentProductMeasurement,
    AssessmentProductMeasurementItem,
    Venue,
)
from app.internal.services.access_decision_service import AccessDecisionService


READ_PERMISSION = "assessment.assignment.read"
MANAGE_PERMISSION = "assessment.assignment.manage"
MAX_ITEMS = 200
MAX_COMMENT = 10_000
_THREE = Decimal("3")
_NINE = Decimal("9")
_HUNDRED = Decimal("100")


class ProductMeasurementPermissionDenied(Exception):
    pass


class ProductMeasurementNotFound(Exception):
    pass


class ProductMeasurementConflict(Exception):
    pass


class ProductMeasurementInvalid(Exception):
    pass


@dataclass(frozen=True)
class ProductItemInput:
    position_type: str
    position_name: str
    taste_score: Decimal
    appearance_score: Decimal
    output_score: Decimal
    ticket_time_score: Decimal
    planned_quantity: Decimal
    actual_quantity: Decimal
    quantity_unit: str
    planned_ticket_seconds: int
    actual_ticket_seconds: int
    comment: str | None


def calculate_product_result(items: list[ProductItemInput]) -> dict[str, Any]:
    """Reproduce the source 9-point taste and 3-point speed scales."""
    checked = [_validate_item(item) for item in items]
    if not checked:
        raise ProductMeasurementInvalid("measurement requires items")
    taste_numerator = sum(
        (
            item.taste_score + item.appearance_score + item.output_score
            for item in checked
        ),
        Decimal("0"),
    )
    taste_denominator = _NINE * len(checked)
    speed_numerator = sum((item.ticket_time_score for item in checked), Decimal("0"))
    speed_denominator = _THREE * len(checked)
    item_results = []
    for index, item in enumerate(checked):
        item_taste = item.taste_score + item.appearance_score + item.output_score
        item_speed = item.ticket_time_score
        item_results.append(
            {
                "position_index": index,
                "position_type": item.position_type,
                "taste": _component(item_taste, _NINE),
                "speed": _component(item_speed, _THREE),
                "overall": _component(item_taste + item_speed, Decimal("12")),
            }
        )
    return {
        "scoring_algorithm": "product_measurement_v1",
        "scoring_version": 1,
        "item_count": len(checked),
        "taste": _component(taste_numerator, taste_denominator),
        "speed": _component(speed_numerator, speed_denominator),
        "overall": _component(
            taste_numerator + speed_numerator,
            Decimal("12") * len(checked),
        ),
        "items": item_results,
    }


def _component(numerator: Decimal, denominator: Decimal) -> dict[str, str]:
    score = (numerator / denominator * _HUNDRED).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return {
        "numerator": format(numerator, "f"),
        "denominator": format(denominator, "f"),
        "score_percent": format(score, "f"),
        "coverage": "1.000000",
    }


def _validate_item(item: ProductItemInput) -> ProductItemInput:
    if item.position_type not in {"dish", "drink"}:
        raise ProductMeasurementInvalid("invalid position type")
    if not item.position_name.strip() or len(item.position_name.strip()) > 255:
        raise ProductMeasurementInvalid("invalid position name")
    for value in (
        item.taste_score,
        item.appearance_score,
        item.output_score,
        item.ticket_time_score,
    ):
        if not value.is_finite() or value < 0 or value > _THREE:
            raise ProductMeasurementInvalid("score must be between zero and three")
    if (
        not item.planned_quantity.is_finite()
        or not item.actual_quantity.is_finite()
        or item.planned_quantity < 0
        or item.actual_quantity < 0
        or item.planned_quantity > Decimal("99999999999999.9999")
        or item.actual_quantity > Decimal("99999999999999.9999")
    ):
        raise ProductMeasurementInvalid("invalid quantity")
    if item.quantity_unit not in {"g", "ml"}:
        raise ProductMeasurementInvalid("invalid quantity unit")
    if not 0 <= item.planned_ticket_seconds <= 86_400:
        raise ProductMeasurementInvalid("invalid planned ticket time")
    if not 0 <= item.actual_ticket_seconds <= 86_400:
        raise ProductMeasurementInvalid("invalid actual ticket time")
    comment = item.comment.strip() if item.comment else None
    if comment and len(comment) > MAX_COMMENT:
        raise ProductMeasurementInvalid("comment too long")
    return ProductItemInput(
        **{
            **item.__dict__,
            "position_name": item.position_name.strip(),
            "comment": comment,
        }
    )


class AssessmentProductMeasurementService:
    """Caller-owned transaction; completed measurements are immutable."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        account_id: UUID,
        company_id: UUID,
        request_id: UUID,
        venue_id: UUID,
        now: datetime,
    ) -> dict[str, Any]:
        checked_now = self._aware(now)
        await self._require_manage(account_id, company_id, checked_now)
        exists = await self._session.scalar(
            select(Venue.id).where(
                Venue.id == venue_id,
                Venue.company_id == company_id,
                Venue.status == "active",
                Venue.deleted_at.is_(None),
            )
        )
        if exists is None:
            raise ProductMeasurementNotFound("venue not found")
        existing = await self._session.get(AssessmentProductMeasurement, request_id)
        if existing is not None:
            if (
                existing.company_id != company_id
                or existing.venue_id != venue_id
                or existing.status != "draft"
            ):
                raise ProductMeasurementConflict(
                    "measurement request conflicts with existing state"
                )
            return await self._document(existing)
        measurement = AssessmentProductMeasurement(
            id=request_id,
            company_id=company_id,
            venue_id=venue_id,
            status="draft",
            revision=0,
            started_at=checked_now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(measurement)
                await self._session.flush()
        except IntegrityError as error:
            existing = await self._session.get(AssessmentProductMeasurement, request_id)
            if (
                existing is None
                or existing.company_id != company_id
                or existing.venue_id != venue_id
                or existing.status != "draft"
            ):
                raise ProductMeasurementConflict(
                    "measurement request conflicts with existing state"
                ) from error
            measurement = existing
        return await self._document(measurement)

    async def replace(
        self,
        account_id: UUID,
        company_id: UUID,
        measurement_id: UUID,
        expected_revision: int,
        items: list[ProductItemInput],
        now: datetime,
    ) -> dict[str, Any]:
        checked_now = self._aware(now)
        await self._require_manage(account_id, company_id, checked_now)
        if len(items) > MAX_ITEMS:
            raise ProductMeasurementInvalid("too many measurement items")
        checked = [_validate_item(item) for item in items]
        measurement = await self._locked(company_id, measurement_id)
        if measurement.status != "draft":
            raise ProductMeasurementConflict("completed measurement is immutable")
        if measurement.revision != expected_revision:
            raise ProductMeasurementConflict("measurement revision conflict")
        await self._session.execute(
            delete(AssessmentProductMeasurementItem).where(
                AssessmentProductMeasurementItem.measurement_id == measurement.id
            )
        )
        for index, item in enumerate(checked):
            self._session.add(
                AssessmentProductMeasurementItem(
                    id=uuid4(),
                    measurement_id=measurement.id,
                    sort_order=index,
                    **item.__dict__,
                )
            )
        measurement.revision += 1
        await self._session.flush()
        return await self._document(measurement)

    async def complete(
        self,
        account_id: UUID,
        company_id: UUID,
        measurement_id: UUID,
        expected_revision: int,
        now: datetime,
    ) -> dict[str, Any]:
        checked_now = self._aware(now)
        await self._require_manage(account_id, company_id, checked_now)
        measurement = await self._locked(company_id, measurement_id)
        if measurement.status == "completed":
            return await self._document(measurement)
        if measurement.revision != expected_revision:
            raise ProductMeasurementConflict("measurement revision conflict")
        rows = (
            (
                await self._session.execute(
                    select(AssessmentProductMeasurementItem)
                    .where(
                        AssessmentProductMeasurementItem.measurement_id
                        == measurement.id
                    )
                    .order_by(AssessmentProductMeasurementItem.sort_order)
                )
            )
            .scalars()
            .all()
        )
        result = calculate_product_result(
            [
                ProductItemInput(
                    **{
                        name: getattr(row, name)
                        for name in ProductItemInput.__dataclass_fields__
                    }
                )
                for row in rows
            ]
        )
        definitions = {
            row.code: row
            for row in (
                await self._session.execute(
                    select(AssessmentMetricDefinition).where(
                        AssessmentMetricDefinition.code.in_(["taste", "speed"]),
                        AssessmentMetricDefinition.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        }
        if set(definitions) != {"taste", "speed"}:
            raise ProductMeasurementInvalid("metric taxonomy is unavailable")
        for code in ("taste", "speed"):
            component = result[code]
            self._session.add(
                AssessmentMetricObservation(
                    id=uuid4(),
                    company_id=company_id,
                    venue_id=measurement.venue_id,
                    attempt_id=None,
                    product_measurement_id=measurement.id,
                    metric_definition_id=definitions[code].id,
                    source_type="measurement",
                    scoring_algorithm="product_measurement_v1",
                    scoring_version=1,
                    numerator=Decimal(component["numerator"]),
                    denominator=Decimal(component["denominator"]),
                    score_percent=Decimal(component["score_percent"]),
                    coverage=Decimal("1"),
                    status="complete",
                    critical_failure_count=0,
                    observed_at=checked_now,
                    stop_factor_count=0,
                    detail_json={
                        "items": [
                            {
                                "position_index": index,
                                "position_type": item.position_type,
                            }
                            for index, item in enumerate(rows)
                        ]
                    },
                )
            )
        measurement.status = "completed"
        measurement.completed_at = checked_now
        measurement.result_json = result
        await self._session.flush()
        return await self._document(measurement)

    async def _locked(
        self, company_id: UUID, measurement_id: UUID
    ) -> AssessmentProductMeasurement:
        value = await self._session.scalar(
            select(AssessmentProductMeasurement)
            .where(
                AssessmentProductMeasurement.id == measurement_id,
                AssessmentProductMeasurement.company_id == company_id,
            )
            .with_for_update()
        )
        if value is None:
            raise ProductMeasurementNotFound("measurement not found")
        return value

    async def _document(
        self, measurement: AssessmentProductMeasurement
    ) -> dict[str, Any]:
        rows = (
            (
                await self._session.execute(
                    select(AssessmentProductMeasurementItem)
                    .where(
                        AssessmentProductMeasurementItem.measurement_id
                        == measurement.id
                    )
                    .order_by(AssessmentProductMeasurementItem.sort_order)
                )
            )
            .scalars()
            .all()
        )
        return {
            "id": measurement.id,
            "company_id": measurement.company_id,
            "venue_id": measurement.venue_id,
            "status": measurement.status,
            "revision": measurement.revision,
            "started_at": measurement.started_at,
            "completed_at": measurement.completed_at,
            "result": measurement.result_json,
            "items": [
                {
                    name: getattr(row, name)
                    for name in ProductItemInput.__dataclass_fields__
                }
                for row in rows
            ],
        }

    async def _require_manage(
        self, account_id: UUID, company_id: UUID, now: datetime
    ) -> None:
        if not await AccessDecisionService(self._session).can_in_company(
            account_id, company_id, MANAGE_PERMISSION, now
        ):
            raise ProductMeasurementPermissionDenied("permission denied")

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ProductMeasurementInvalid("now must be timezone-aware")
        return value.astimezone(timezone.utc)
