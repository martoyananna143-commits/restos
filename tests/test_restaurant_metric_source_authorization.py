"""PostgreSQL authorization regressions for restaurant metric drill-down."""

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.account_auth import get_current_account_principal
from app.api.routers import account_restaurant_metrics
from app.api.routers.account_invitation_auth import get_account_auth_session
from app.infra.database.models import AssessmentMetricObservation
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.account_organization_access_service import (
    AccountOrganizationAccessService,
    ReplaceEmployeeAccess,
)
from app.internal.services.assessment_metric_dashboard_service import (
    AssessmentMetricDashboardPermissionDenied,
    AssessmentMetricDashboardService,
)
from tests.test_account_organization_access_service import (
    create_organization,
    create_venue,
    join_employee,
)
from tests.test_assessment_metric_dashboard_period import (
    _import_published_version,
    _submit_walkthrough,
)


NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


async def _replace_access(
    session: AsyncSession,
    owner,
    company,
    membership,
    profile: str,
    venue_ids: tuple[UUID, ...],
) -> None:
    service = AccountOrganizationAccessService(session)
    current = await service.employee_access(
        owner.id, company.company_id, membership.employee_profile_id, NOW
    )
    await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            profile,
            venue_ids,
            current["revision"],
            NOW + timedelta(seconds=1),
        )
    )


async def _context(session: AsyncSession):
    owner, company = await create_organization(session, "Metric source scope")
    second = await create_venue(session, owner, company, "Second")
    manager, manager_membership = await join_employee(
        session, owner, company, company.venue_id, "Venue manager"
    )
    organization_manager, organization_membership = await join_employee(
        session, owner, company, None, "Organization manager"
    )
    unbound, _ = await join_employee(session, owner, company, None, "Unbound")
    await _replace_access(
        session,
        owner,
        company,
        manager_membership,
        "venue_manager",
        (company.venue_id,),
    )
    await _replace_access(
        session,
        owner,
        company,
        organization_membership,
        "organization_manager",
        (),
    )
    imported = await _import_published_version(
        session,
        company.company_id,
        "restaurant-service-walkthrough.json",
        NOW - timedelta(days=2),
    )
    first_company = SimpleNamespace(
        company_id=company.company_id, venue_id=company.venue_id
    )
    second_company = SimpleNamespace(
        company_id=company.company_id, venue_id=second["venue_id"]
    )
    await _submit_walkthrough(
        session,
        owner,
        first_company,
        imported.template_version_id,
        NOW - timedelta(minutes=2),
    )
    await _submit_walkthrough(
        session,
        owner,
        second_company,
        imported.template_version_id,
        NOW - timedelta(minutes=1),
    )
    return SimpleNamespace(
        owner=owner,
        company=company,
        second_venue_id=second["venue_id"],
        manager=manager,
        organization_manager=organization_manager,
        unbound=unbound,
    )


@pytest.mark.asyncio
async def test_sources_apply_owner_company_and_explicit_venue_scope_before_limit():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        context = await _context(session)
        service = AssessmentMetricDashboardService(session)

        owner_rows = await service.sources(
            context.owner.id,
            context.company.company_id,
            "food_safety",
            NOW,
            venue_id=None,
            source_type=None,
            section_code=None,
            limit=50,
        )
        organization_rows = await service.sources(
            context.organization_manager.id,
            context.company.company_id,
            "food_safety",
            NOW,
            venue_id=None,
            source_type=None,
            section_code=None,
            limit=50,
        )
        manager_rows = await service.sources(
            context.manager.id,
            context.company.company_id,
            "food_safety",
            NOW,
            venue_id=None,
            source_type=None,
            section_code=None,
            limit=1,
        )
        assert len(owner_rows) == len(organization_rows) == 2
        assert len(manager_rows) == 1
        authorized_observation = await session.get(
            AssessmentMetricObservation, manager_rows[0]["observation_id"]
        )
        assert authorized_observation is not None
        assert authorized_observation.venue_id == context.company.venue_id

        explicit = await service.sources(
            context.manager.id,
            context.company.company_id,
            "food_safety",
            NOW,
            venue_id=context.company.venue_id,
            source_type="walkthrough",
            section_code=None,
            limit=50,
        )
        assert len(explicit) == 1
        with pytest.raises(AssessmentMetricDashboardPermissionDenied):
            await service.sources(
                context.manager.id,
                context.company.company_id,
                "food_safety",
                NOW,
                venue_id=context.second_venue_id,
                source_type=None,
                section_code=None,
                limit=50,
            )
        with pytest.raises(AssessmentMetricDashboardPermissionDenied):
            await service.sources(
                context.unbound.id,
                context.company.company_id,
                "food_safety",
                NOW,
                venue_id=None,
                source_type=None,
                section_code=None,
                limit=50,
            )
        assert (
            await service.sources(
                context.owner.id,
                context.company.company_id,
                "economics",
                NOW,
                venue_id=None,
                source_type=None,
                section_code=None,
                limit=50,
            )
            == []
        )
        assert await session.scalar(select(1)) == 1
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_food_safety_source_api_is_typed_no_store_and_venue_scoped():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        context = await _context(session)

        async def principal() -> CurrentAccountPrincipal:
            return CurrentAccountPrincipal(
                context.manager.id,
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
                f"/api/v1/account/companies/{context.company.company_id}"
                "/restaurant-metrics/food_safety/sources?limit=50"
            )
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert "set-cookie" not in response.headers
        values = [
            account_restaurant_metrics.MetricSourceDrilldownResponse.model_validate(
                value
            )
            for value in response.json()
        ]
        assert len(values) == 1
        observation = await session.get(
            AssessmentMetricObservation, values[0].observation_id
        )
        assert observation is not None
        assert observation.venue_id == context.company.venue_id
        assert await session.scalar(select(1)) == 1
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()
