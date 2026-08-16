"""PostgreSQL regressions for authoritative local Today metric bounds."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_restaurant_metrics
from app.api.routers.account_invitation_auth import get_account_auth_session
from app.infra.database.models import AssessmentTemplateVersion
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.assessment_attempt_service import (
    AnswerInput,
    AssessmentAttemptService,
    ReplaceDraft,
)
from app.internal.services.assessment_management_service import (
    AssessmentManagementService,
    CreateAssignment,
)
from app.internal.services.assessment_metric_dashboard_service import (
    AssessmentMetricDashboardInvalid,
    AssessmentMetricDashboardPermissionDenied,
    AssessmentMetricDashboardService,
)
from app.internal.services.assessment_operational_walkthrough_service import (
    AssessmentOperationalWalkthroughService,
)
from app.internal.services.assessment_template_import_service import (
    AssessmentTemplateImportService,
    ReviewedManifest,
)
from app.internal.services.assessment_template_service import (
    AssessmentTemplateService,
    PublishMethodology,
    PublishTemplateVersion,
)
from tests.test_account_organization_access_service import create_organization


CAPTURED_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
MANIFESTS = (
    Path(__file__).parents[1]
    / "app/internal/data/assessment_template_import/manifests"
)


async def _import_published_version(
    session: AsyncSession,
    company_id,
    manifest_name: str,
    now: datetime,
):
    imported = await AssessmentTemplateImportService(session).apply(
        company_id,
        ReviewedManifest.parse((MANIFESTS / manifest_name).read_bytes()),
        now,
    )
    version = await session.get(
        AssessmentTemplateVersion, imported.template_version_id
    )
    assert version is not None
    lifecycle = AssessmentTemplateService(session)
    await lifecycle.publish_methodology(
        PublishMethodology(version.methodology_id, now + timedelta(seconds=1))
    )
    await lifecycle.publish_template_version(
        PublishTemplateVersion(
            imported.template_id,
            imported.template_version_id,
            now + timedelta(seconds=2),
        )
    )
    return imported


async def _replace_and_submit(
    session: AsyncSession,
    account_id,
    document: dict,
    submitted_at: datetime,
    answer: bool,
) -> dict:
    answers = [
        AnswerInput(item["id"], item["answer_type"], answer)
        for section in document["document"]["sections"]
        for item in section["items"]
    ]
    assert answers and all(value.answer_type == "boolean" for value in answers)
    attempts = AssessmentAttemptService(session)
    await attempts.replace_draft(
        ReplaceDraft(
            account_id,
            document["id"],
            document["revision"],
            answers,
            submitted_at - timedelta(seconds=1),
        )
    )
    return await attempts.submit(account_id, document["id"], submitted_at)


async def _submit_evaluation(
    session: AsyncSession,
    owner,
    company,
    template_version_id,
    submitted_at: datetime,
    answer: bool,
) -> dict:
    assignment = await AssessmentManagementService(session).create_assignment(
        CreateAssignment(
            owner.id,
            company.company_id,
            company.employee_profile_id,
            template_version_id,
            None,
            submitted_at + timedelta(days=1),
            submitted_at - timedelta(minutes=2),
        )
    )
    document = await AssessmentAttemptService(session).create_or_resume(
        owner.id,
        assignment["id"],
        submitted_at - timedelta(minutes=1),
    )
    return await _replace_and_submit(
        session, owner.id, document, submitted_at, answer
    )


async def _submit_walkthrough(
    session: AsyncSession,
    owner,
    company,
    template_version_id,
    submitted_at: datetime,
) -> dict:
    assert company.venue_id is not None
    document = await AssessmentOperationalWalkthroughService(session).start(
        owner.id,
        company.company_id,
        company.venue_id,
        template_version_id,
        submitted_at - timedelta(minutes=1),
    )
    return await _replace_and_submit(
        session, owner.id, document, submitted_at, True
    )


def _component(result: dict, code: str, source_type: str = "evaluation") -> dict:
    metric = next(value for value in result["metrics"] if value["code"] == code)
    return next(
        value
        for value in metric["components"]
        if value["source_type"] == source_type
    )


@pytest.mark.asyncio
async def test_today_dashboard_uses_elapsed_window_and_excludes_future() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        owner, company = await create_organization(session, "Today Period")
        evaluation = await _import_published_version(
            session,
            company.company_id,
            "cook-kln.json",
            CAPTURED_NOW - timedelta(days=4),
        )
        current_from, current_to, previous_from, previous_to = (
            AssessmentMetricDashboardService._period_bounds(
                CAPTURED_NOW, "Europe/Moscow", "today"
            )
        )
        for observed_at, answer in (
            (current_from - timedelta(microseconds=1), False),
            (current_from, True),
            (current_to - timedelta(microseconds=1), True),
            (current_to, False),
            (previous_from, False),
            (previous_to - timedelta(microseconds=1), False),
            (previous_to, True),
        ):
            await _submit_evaluation(
                session,
                owner,
                company,
                evaluation.template_version_id,
                observed_at,
                answer,
            )

        service = AssessmentMetricDashboardService(session)
        result = await service.dashboard(
            owner.id,
            company.company_id,
            CAPTURED_NOW,
            venue_id=None,
            source_type=None,
            section_code=None,
            from_at=None,
            to_at=None,
            period="today",
            compare_previous=True,
        )
        assert result["from_at"] == current_from
        assert result["to_at"] == current_to == CAPTURED_NOW
        assert result["comparison_from_at"] == previous_from
        assert result["comparison_to_at"] == previous_to
        component = _component(result, "people")
        assert component["observation_count"] == 2
        assert component["score_percent"] == "100.0000"
        assert component["comparison_status"] == "comparable"
        assert component["delta"] == "100.0000"
        assert component["delta_unit"] == "percentage_points"

        walkthrough = await _import_published_version(
            session,
            company.company_id,
            "restaurant-service-walkthrough.json",
            CAPTURED_NOW - timedelta(days=3),
        )
        await _submit_walkthrough(
            session,
            owner,
            company,
            walkthrough.template_version_id,
            previous_from + timedelta(hours=1),
        )
        mismatch = await service.dashboard(
            owner.id,
            company.company_id,
            CAPTURED_NOW,
            venue_id=None,
            source_type=None,
            section_code=None,
            from_at=None,
            to_at=None,
            period="today",
            compare_previous=True,
        )
        assert _component(mismatch, "people")["comparison_status"] == "not_comparable"

        local_midnight = datetime(2026, 8, 16, 21, 0, tzinfo=timezone.utc)
        empty = await service.dashboard(
            owner.id,
            company.company_id,
            local_midnight,
            venue_id=None,
            source_type=None,
            section_code=None,
            from_at=None,
            to_at=None,
            period="today",
            compare_previous=True,
        )
        assert empty["from_at"] == empty["to_at"] == local_midnight

        with pytest.raises(AssessmentMetricDashboardInvalid):
            await service.dashboard(
                owner.id,
                company.company_id,
                CAPTURED_NOW,
                venue_id=None,
                source_type=None,
                section_code=None,
                from_at=CAPTURED_NOW - timedelta(hours=1),
                to_at=CAPTURED_NOW + timedelta(microseconds=1),
            )

        foreign_owner, foreign = await create_organization(session, "Foreign Period")
        assert foreign_owner.id != owner.id
        with pytest.raises(AssessmentMetricDashboardPermissionDenied):
            await service.dashboard(
                owner.id,
                foreign.company_id,
                CAPTURED_NOW,
                venue_id=None,
                source_type=None,
                section_code=None,
                from_at=None,
                to_at=None,
                period="today",
                compare_previous=True,
            )
        assert await session.scalar(select(1)) == 1
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_today_api_returns_typed_http_200_with_no_store() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        owner, company = await create_organization(session, "Today API")

        async def principal() -> CurrentAccountPrincipal:
            return CurrentAccountPrincipal(
                owner.id,
                uuid4(),
                uuid4(),
                1,
                datetime.now(timezone.utc) + timedelta(minutes=5),
            )

        async def database():
            yield session

        application = FastAPI()
        application.include_router(account_restaurant_metrics.router)
        application.dependency_overrides[get_current_account_principal] = principal
        application.dependency_overrides[get_account_auth_session] = database
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                f"/api/v1/account/companies/{company.company_id}/restaurant-metrics",
                params={"period": "today", "compare_previous": "true"},
            )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert "set-cookie" not in response.headers
        validated = (
            account_restaurant_metrics.RestaurantMetricDashboardResponse.model_validate(
                response.json()
            )
        )
        assert validated.to_at <= datetime.now(timezone.utc)
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
