"""Pure product-decision regressions for authorized assessment journeys."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.internal.services.assessment_attempt_service import (
    AssessmentAssignmentPeriodInvalid,
    AssessmentAttemptService,
)
from app.internal.services.assessment_metric_dashboard_service import (
    AssessmentMetricDashboardService,
)


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("period", "expected_start", "expected_end"),
    [
        ("today", datetime(2026, 8, 13, 21, tzinfo=timezone.utc), datetime(2026, 8, 14, 21, tzinfo=timezone.utc)),
        ("yesterday", datetime(2026, 8, 12, 21, tzinfo=timezone.utc), datetime(2026, 8, 13, 21, tzinfo=timezone.utc)),
        ("previous_week", datetime(2026, 8, 2, 21, tzinfo=timezone.utc), datetime(2026, 8, 9, 21, tzinfo=timezone.utc)),
        ("previous_month", datetime(2026, 6, 30, 21, tzinfo=timezone.utc), datetime(2026, 7, 31, 21, tzinfo=timezone.utc)),
    ],
)
def test_history_periods_use_completed_local_calendar_boundaries(
    period, expected_start, expected_end
) -> None:
    start, end = AssessmentAttemptService._history_bounds(
        NOW, "Europe/Moscow", period, None, None
    )
    assert (start, end) == (expected_start, expected_end)


def test_custom_history_period_is_inclusive_and_rejects_invalid_range() -> None:
    start, end = AssessmentAttemptService._history_bounds(
        NOW,
        "Europe/Moscow",
        "custom",
        date(2026, 2, 28),
        date(2026, 3, 1),
    )
    assert start == datetime(2026, 2, 27, 21, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 1, 21, tzinfo=timezone.utc)
    with pytest.raises(AssessmentAssignmentPeriodInvalid):
        AssessmentAttemptService._history_bounds(
            NOW,
            "Europe/Moscow",
            "custom",
            date(2026, 3, 2),
            date(2026, 3, 1),
        )


def test_today_metric_bounds_use_company_timezone_and_previous_operational_day() -> None:
    current_from, current_to, previous_from, previous_to = (
        AssessmentMetricDashboardService._period_bounds(
            NOW, "Europe/Moscow", "today"
        )
    )
    assert current_from == datetime(2026, 8, 13, 21, tzinfo=timezone.utc)
    assert current_to == NOW
    assert previous_from == datetime(2026, 8, 12, 21, tzinfo=timezone.utc)
    assert previous_to == datetime(2026, 8, 13, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "captured_now",
    [
        datetime(2026, 8, 14, 5, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc),
    ],
)
def test_today_metric_bounds_end_at_one_captured_server_now(
    captured_now: datetime,
) -> None:
    current_from, current_to, previous_from, previous_to = (
        AssessmentMetricDashboardService._period_bounds(
            captured_now, "Europe/Moscow", "today"
        )
    )
    assert current_from == datetime(2026, 8, 13, 21, tzinfo=timezone.utc)
    assert current_to == captured_now
    assert previous_from == datetime(2026, 8, 12, 21, tzinfo=timezone.utc)
    assert previous_to == captured_now - timedelta(days=1)


def test_today_metric_bounds_allow_an_empty_interval_at_local_midnight() -> None:
    local_midnight = datetime(2026, 8, 14, 21, 0, tzinfo=timezone.utc)
    current_from, current_to, previous_from, previous_to = (
        AssessmentMetricDashboardService._period_bounds(
            local_midnight, "Europe/Moscow", "today"
        )
    )
    assert current_from == current_to == local_midnight
    assert previous_from == previous_to == datetime(
        2026, 8, 13, 21, 0, tzinfo=timezone.utc
    )


@pytest.mark.parametrize(
    ("captured_now", "expected"),
    [
        (
            datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc),
            (
                datetime(2026, 3, 28, 23, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc),
                datetime(2026, 3, 27, 23, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 28, 2, 30, tzinfo=timezone.utc),
            ),
        ),
        (
            datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc),
            (
                datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc),
                datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc),
                datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc),
                datetime(2026, 10, 24, 0, 30, tzinfo=timezone.utc),
            ),
        ),
    ],
)
def test_today_metric_bounds_use_local_wall_clock_across_dst(
    captured_now: datetime,
    expected: tuple[datetime, datetime, datetime, datetime],
) -> None:
    assert (
        AssessmentMetricDashboardService._period_bounds(
            captured_now, "Europe/Berlin", "today"
        )
        == expected
    )


def test_low_indicator_ranking_requires_three_samples_shares_ties_and_is_bounded() -> None:
    attempts = [uuid4() for _ in range(4)]
    first, tied, insufficient = uuid4(), uuid4(), uuid4()
    values = {
        first: {
            attempt: {"score": Decimal("0.2"), "critical": False, "stop_factor": False}
            for attempt in attempts[:3]
        },
        tied: {
            attempt: {"score": Decimal("0.2"), "critical": attempt == attempts[0], "stop_factor": False}
            for attempt in attempts
        },
        insufficient: {
            attempt: {"score": Decimal("0"), "critical": False, "stop_factor": True}
            for attempt in attempts[:2]
        },
    }
    ranked = AssessmentMetricDashboardService._rank_low_indicators(
        values,
        {
            first: ("a-item", "Первый показатель"),
            tied: ("b-item", "Второй показатель"),
            insufficient: ("c-item", "Недостаточно данных"),
        },
        observation_count=4,
    )
    assert [value["rank"] for value in ranked] == [1, 1]
    assert [value["sample_count"] for value in ranked] == [3, 4]
    assert ranked[0]["coverage"] == "0.750000"
    assert ranked[1]["critical_failure_count"] == 1
    assert all("stop_factor_failure" not in value for value in ranked)
