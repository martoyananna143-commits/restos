"""PDF rendering and bounded-security contracts for immutable results."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from pypdf import PdfReader
import pytest

from app.internal.services.assessment_result_pdf_service import (
    MAX_PDF_ITEMS,
    AssessmentResultPdfInvalid,
    AssessmentResultPdfService,
)


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def projection(item_count=2):
    return {
        "attempt_id": "internal-attempt-id-must-not-render",
        "company_id": "internal-company-id-must-not-render",
        "phone": "+79991234567",
        "date_of_birth": "01.01.1990",
        "access_token": "synthetic-token",
        "venue_id": None,
        "template_name": "КЛН официанта",
        "template_version": 3,
        "status": "completed",
        "venue_name": "Синтетический ресторан",
        "subject_name": "Синтетический сотрудник",
        "submitted_at": NOW,
        "local_submitted_at": "2026-08-17T15:00:00+03:00",
        "timezone": "Europe/Moscow",
        "scoring_algorithm": "weighted_v1",
        "score_percent": "87.5000",
        "score_display": "88%",
        "answered_count": item_count,
        "required_count": item_count,
        "total_count": item_count,
        "critical_failure_count": 0,
        "stop_factor_count": 0,
        "sections": [
            {
                "title": "Подготовка",
                "score_percent": "87.5000",
                "score_display": "88%",
                "coverage": "1.000000",
                "critical_failure_count": 0,
                "stop_factor_count": 0,
                "items": [
                    {
                        "prompt": f"Вопрос {index + 1}",
                        "answer_type": "boolean",
                        "value": "Да",
                        "comment": "Безопасное наблюдение",
                    }
                    for index in range(item_count)
                ],
            }
        ],
        "related_tasks": [{"title": "Исправить стандарт", "status": "assigned"}],
    }


def test_pdf_is_in_memory_parseable_cyrillic_and_uses_display_integer():
    content = AssessmentResultPdfService().generate(projection(), NOW)
    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert content.startswith(b"%PDF-")
    assert "КЛН официанта" in text
    assert "Синтетический ресторан" in text
    assert "88%" in text
    assert "17 августа 2026, 15:00" in text
    assert "Назначена" in text
    assert "assigned" not in text
    assert "Europe/Moscow" not in text
    assert "2026-08-17T" not in text
    assert "87.5000" not in text
    assert "internal-attempt-id-must-not-render" not in text
    assert "internal-company-id-must-not-render" not in text
    for forbidden in ("+79991234567", "01.01.1990", "synthetic-token"):
        assert forbidden not in text


def test_pdf_supports_multipage_results_and_repeats_safe_footer():
    content = AssessmentResultPdfService().generate(projection(90), NOW)
    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) >= 2
    assert all("RestOS" in (page.extract_text() or "") for page in reader.pages)
    assert all("1. Подготовка" in (page.extract_text() or "") for page in reader.pages[:-1])


def test_pdf_does_not_create_an_almost_empty_task_page_and_handles_long_text():
    value = projection(48)
    value["template_name"] = "Очень длинное название методики " * 8
    value["sections"][0]["items"][0]["prompt"] = "Длинный вопрос " * 80
    value["sections"][0]["items"][0]["comment"] = "Подробное наблюдение " * 120
    value["related_tasks"] = [
        {"title": "Единственная связанная задача", "status": "assigned"}
    ]
    content = AssessmentResultPdfService().generate(value, NOW)
    reader = PdfReader(BytesIO(content))
    texts = [page.extract_text() or "" for page in reader.pages]
    assert len(texts) >= 2
    assert "Связанные задачи" in "\n".join(texts)
    assert "Назначена" in "\n".join(texts)
    assert all(len(text.strip()) > 120 for text in texts)


def test_pdf_rejects_non_completed_unbounded_and_naive_inputs():
    invalid = projection()
    invalid["status"] = "draft"
    with pytest.raises(AssessmentResultPdfInvalid):
        AssessmentResultPdfService().generate(invalid, NOW)
    with pytest.raises(AssessmentResultPdfInvalid):
        AssessmentResultPdfService().generate(projection(MAX_PDF_ITEMS + 1), NOW)
    with pytest.raises(AssessmentResultPdfInvalid):
        AssessmentResultPdfService().generate(
            projection(), datetime(2026, 8, 17, 12, 0)
        )


def test_concurrent_pdf_requests_are_bounded_independent_and_parseable():
    service = AssessmentResultPdfService()
    service.generate(projection(), NOW)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda count: service.generate(projection(count), NOW),
                (1, 2, 3, 4),
            )
        )
    assert len(results) == 4
    assert all(value.startswith(b"%PDF-") for value in results)
    assert all(len(PdfReader(BytesIO(value)).pages) >= 1 for value in results)
