"""Pure contracts for assessment history cursors, grouping and presentation."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.internal.services.assessment_history_service import (
    AssessmentHistoryInvalid,
    AssessmentHistoryService,
)
from app.internal.services.presentation_percent import (
    PresentationPercentInvalid,
    format_percent,
    format_percentage_points,
)


def test_history_cursor_round_trip_is_stable_and_opaque():
    event_at = datetime(2026, 8, 17, 12, 34, 56, tzinfo=timezone.utc)
    attempt_id = uuid4()
    encoded = AssessmentHistoryService._encode_cursor(event_at, attempt_id)
    decoded = AssessmentHistoryService._decode_cursor(encoded)
    assert decoded.event_at == event_at
    assert decoded.attempt_id == attempt_id
    assert str(attempt_id) not in encoded


@pytest.mark.parametrize(
    "value",
    ["", "not-base64", "e30", "a" * 257],
)
def test_history_cursor_rejects_malformed_or_oversized_values(value):
    with pytest.raises(AssessmentHistoryInvalid, match="history cursor is invalid"):
        AssessmentHistoryService._decode_cursor(value)


def test_history_day_labels_are_local_calendar_labels():
    today = date(2026, 8, 17)
    assert AssessmentHistoryService._day_label(today, today) == "Сегодня, 17 августа"
    assert AssessmentHistoryService._day_label(date(2026, 8, 16), today) == (
        "Вчера, 16 августа"
    )
    assert AssessmentHistoryService._day_label(date(2026, 7, 31), today) == "31 июля"
    assert AssessmentHistoryService._day_label(date(2025, 12, 31), today) == (
        "31 декабря 2025"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("87.49", "87%"),
        ("87.50", "88%"),
        ("99.50", "100%"),
        ("0.49", "0%"),
        ("100.0000", "100%"),
    ],
)
def test_percentage_display_uses_round_half_up_without_mutating_input(value, expected):
    assert format_percent(value) == expected
    assert value == value


def test_percentage_point_display_and_invalid_values_are_controlled():
    assert format_percentage_points("3.5") == "+4 п.п."
    assert format_percentage_points("-3.5") == "-4 п.п."
    with pytest.raises(PresentationPercentInvalid):
        format_percent("NaN")


def test_choice_answer_projection_never_exposes_option_uuid_as_visible_text():
    option_id = uuid4()
    labels = {option_id: "Безопасный вариант"}
    assert (
        AssessmentHistoryService._display_answer(
            "single_choice", str(option_id), labels
        )
        == "Безопасный вариант"
    )
    assert AssessmentHistoryService._display_answer(
        "multi_choice", [str(option_id)], labels
    ) == ["Безопасный вариант"]
    assert str(option_id) not in str(
        AssessmentHistoryService._display_answer(
            "single_choice", str(option_id), labels
        )
    )
