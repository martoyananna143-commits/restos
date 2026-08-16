from decimal import Decimal
from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models import Venue

from app.internal.services.assessment_product_measurement_service import (
    AssessmentProductMeasurementService,
    ProductItemInput,
    ProductMeasurementInvalid,
    calculate_product_result,
)
from tests.test_assessment_attempt_service import seed_context


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def item(**overrides):
    values = {
        "position_type": "dish",
        "position_name": "Тестовая позиция",
        "taste_score": Decimal("3"),
        "appearance_score": Decimal("2"),
        "output_score": Decimal("1"),
        "ticket_time_score": Decimal("2"),
        "planned_quantity": Decimal("200"),
        "actual_quantity": Decimal("195"),
        "quantity_unit": "g",
        "planned_ticket_seconds": 600,
        "actual_ticket_seconds": 640,
        "comment": None,
    }
    values.update(overrides)
    return ProductItemInput(**values)


def test_product_measurement_uses_explicit_nine_and_three_point_scales():
    result = calculate_product_result([item()])
    assert result["taste"] == {
        "numerator": "6",
        "denominator": "9",
        "score_percent": "66.6667",
        "coverage": "1.000000",
    }
    assert result["speed"] == {
        "numerator": "2",
        "denominator": "3",
        "score_percent": "66.6667",
        "coverage": "1.000000",
    }
    assert result["overall"] == {
        "numerator": "8",
        "denominator": "12",
        "score_percent": "66.6667",
        "coverage": "1.000000",
    }
    assert result["items"] == [
        {
            "position_index": 0,
            "position_type": "dish",
            "taste": result["taste"],
            "speed": result["speed"],
            "overall": result["overall"],
        }
    ]


def test_product_measurement_is_repeatable_and_has_no_fixed_empty_rows():
    result = calculate_product_result(
        [item(), item(position_type="drink", quantity_unit="ml")]
    )
    assert result["item_count"] == 2


def test_product_measurement_rejects_out_of_range_scores():
    with pytest.raises(ProductMeasurementInvalid):
        calculate_product_result([item(taste_score=Decimal("3.1"))])


def test_product_measurement_rejects_non_finite_quantity():
    with pytest.raises(ProductMeasurementInvalid):
        calculate_product_result([item(actual_quantity=Decimal("NaN"))])


@pytest.mark.asyncio
async def test_create_request_id_is_idempotent_and_venue_is_active():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context = await seed_context(session)
        venue = Venue(
            company_id=context.company.id,
            name="Synthetic restaurant",
            code=f"measurement-{uuid4().hex[:10]}",
            status="active",
            meta={},
        )
        session.add(venue)
        await session.flush()
        request_id = uuid4()
        service = AssessmentProductMeasurementService(session)
        first = await service.create(
            context.account.id,
            context.company.id,
            request_id,
            venue.id,
            NOW,
        )
        second = await service.create(
            context.account.id,
            context.company.id,
            request_id,
            venue.id,
            NOW,
        )
        assert first["id"] == second["id"] == request_id
        await session.rollback()
    await engine.dispose()
