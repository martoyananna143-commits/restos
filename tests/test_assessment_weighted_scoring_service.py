from decimal import Decimal
from uuid import uuid4

import pytest

from app.internal.services.assessment_weighted_scoring_service import (
    MetricMapping,
    WeightedItem,
    WeightedScoringInvalid,
    calculate_metric_results,
    calculate_weighted_result,
)


def item(
    *,
    answer_type: str = "boolean",
    required: bool = True,
    weight: str = "1",
    minimum: str | None = None,
    maximum: str | None = None,
    criticality: str = "normal",
    config: dict | None = None,
    option_values: dict | None = None,
) -> WeightedItem:
    return WeightedItem(
        item_id=uuid4(),
        answer_type=answer_type,
        required=required,
        weight=Decimal(weight),
        min_value=Decimal(minimum) if minimum is not None else None,
        max_value=Decimal(maximum) if maximum is not None else None,
        criticality=criticality,
        config=config or {},
        option_values=option_values or {},
    )


def test_weighted_boolean_score_and_rounding() -> None:
    first = item(weight="1")
    second = item(weight="2")

    result = calculate_weighted_result(
        [first, second], {first.item_id: True, second.item_id: False}
    )

    assert result.numerator == Decimal("1")
    assert result.denominator == Decimal("3")
    assert result.score_percent == Decimal("33.3333")
    assert result.coverage == Decimal("1.000000")


def test_optional_missing_is_not_zero_and_reduces_coverage() -> None:
    answered = item(weight="1")
    not_applicable = item(required=False, weight="3")

    result = calculate_weighted_result(
        [answered, not_applicable], {answered.item_id: True}
    )

    assert result.score_percent == Decimal("100.0000")
    assert result.coverage == Decimal("0.250000")
    assert result.excluded_count == 1


def test_required_missing_fails_closed() -> None:
    required = item()
    with pytest.raises(WeightedScoringInvalid, match="required answer"):
        calculate_weighted_result([required], {})


def test_numeric_range_and_critical_failure() -> None:
    scored = item(
        answer_type="score",
        minimum="0",
        maximum="3",
        criticality="critical",
        config={"critical_threshold": "0.5"},
    )

    result = calculate_weighted_result([scored], {scored.item_id: "1"})

    assert result.score_percent == Decimal("33.3333")
    assert result.critical_failure_count == 1
    assert result.stop_factor_count == 0


def test_stop_factor_is_reported_separately_from_critical_failure() -> None:
    stop = item(criticality="stop_factor", config={"critical_threshold": "1"})
    result = calculate_weighted_result([stop], {stop.item_id: False})
    assert result.critical_failure_count == 0
    assert result.stop_factor_count == 1


def test_choice_requires_explicit_numeric_value() -> None:
    option_id = uuid4()
    scored = item(
        answer_type="single_choice",
        minimum="0",
        maximum="2",
        option_values={option_id: Decimal("2")},
    )
    result = calculate_weighted_result([scored], {scored.item_id: option_id})
    assert result.score_percent == Decimal("100.0000")


def test_metric_projection_keeps_components_separate() -> None:
    taste_item = item(weight="2")
    speed_item = item(weight="1")
    source = calculate_weighted_result(
        [taste_item, speed_item],
        {taste_item.item_id: True, speed_item.item_id: False},
    )
    taste_id = uuid4()
    speed_id = uuid4()

    metrics = calculate_metric_results(
        source,
        [
            MetricMapping(
                taste_item.item_id, taste_id, "taste", Decimal("2"), "positive"
            ),
            MetricMapping(
                speed_item.item_id, speed_id, "speed", Decimal("1"), "positive"
            ),
        ],
    )

    assert {value.metric_code: value.score_percent for value in metrics} == {
        "taste": Decimal("100.0000"),
        "speed": Decimal("0.0000"),
    }


def test_metric_projection_retains_unanswered_mapping_for_section_coverage() -> None:
    answered = item(weight="1")
    omitted = item(required=False, weight="3")
    source = calculate_weighted_result([answered, omitted], {answered.item_id: True})
    metric_id = uuid4()

    metric = calculate_metric_results(
        source,
        [
            MetricMapping(
                answered.item_id,
                metric_id,
                "order",
                Decimal("1"),
                "positive",
            ),
            MetricMapping(
                omitted.item_id,
                metric_id,
                "order",
                Decimal("3"),
                "positive",
            ),
        ],
    )[0]

    assert metric.score_percent == Decimal("100.0000")
    assert metric.coverage == Decimal("0.250000")
    assert len(metric.contributions) == 2
    assert metric.contributions[1]["normalized"] is None
    assert metric.contributions[1]["weight"] == "3"


@pytest.mark.parametrize("weight", ["0", "-1"])
def test_non_positive_weight_is_rejected(weight: str) -> None:
    invalid = item(weight=weight)
    with pytest.raises(WeightedScoringInvalid, match="positive weight"):
        calculate_weighted_result([invalid], {invalid.item_id: True})


def test_public_result_contains_no_item_answers() -> None:
    scored = item()
    result = calculate_weighted_result([scored], {scored.item_id: True})
    document = result.public_document("2026-08-11T00:00:00+00:00")

    assert document["scoring_algorithm"] == "weighted_v1"
    assert "item_scores" not in document
    assert "answers" not in document
