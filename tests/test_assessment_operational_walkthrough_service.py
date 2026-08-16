"""PostgreSQL integration tests for venue-owned operational walkthroughs."""

from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentScoringPolicy,
    Company,
    Venue,
)
from app.internal.services.assessment_operational_walkthrough_service import (
    AssessmentOperationalWalkthroughService,
    OperationalWalkthroughNotFound,
)
from tests.test_assessment_attempt_service import seed_context


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)


async def seed_walkthrough(session: AsyncSession):
    context = await seed_context(session)
    context.template.activity_type = "walkthrough"
    context.assignment.status = "completed"
    context.assignment.completed_at = NOW
    venue = Venue(
        company_id=context.company.id,
        name="Synthetic restaurant",
        code=f"restaurant-{uuid4().hex[:10]}",
        status="active",
        meta={},
    )
    session.add_all(
        [
            venue,
            AssessmentScoringPolicy(
                template_version_id=context.version.id,
                algorithm="weighted_v1",
                version=1,
                config={},
            ),
        ]
    )
    await session.flush()
    return context, venue


@pytest.mark.asyncio
async def test_walkthrough_is_venue_owned_and_double_start_resumes_one_attempt():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context, venue = await seed_walkthrough(session)
        service = AssessmentOperationalWalkthroughService(session)
        templates = await service.list_templates(
            context.account.id, context.company.id, NOW
        )
        assert templates == [
            {
                "template_id": context.template.id,
                "template_version_id": context.version.id,
                "name": "Pilot assessment",
                "version": 1,
                "section_count": 1,
                "item_count": 2,
                "scoring_algorithm": "weighted_v1",
                "scoring_ready": True,
            }
        ]
        first = await service.start(
            context.account.id,
            context.company.id,
            venue.id,
            context.version.id,
            NOW,
        )
        second = await service.start(
            context.account.id,
            context.company.id,
            venue.id,
            context.version.id,
            NOW,
        )
        assert first["id"] == second["id"]
        assignment = await session.get(AssessmentAssignment, first["assignment_id"])
        assert assignment.purpose == "operational_walkthrough"
        assert assignment.venue_id == venue.id
        assert assignment.employee_profile_id == context.profile.id
        assert (
            await session.scalar(
                select(func.count(AssessmentAttempt.id)).where(
                    AssessmentAttempt.assignment_id == assignment.id
                )
            )
            == 1
        )
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_foreign_company_venue_fails_closed_without_assignment():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context, _ = await seed_walkthrough(session)
        foreign = Company(
            owner_account_id=context.account.id,
            name="Foreign",
            code=f"foreign-{uuid4().hex[:10]}",
            timezone="UTC",
            locale="ru-RU",
            status="active",
        )
        session.add(foreign)
        await session.flush()
        venue = Venue(
            company_id=foreign.id,
            name="Foreign restaurant",
            code=f"foreign-restaurant-{uuid4().hex[:8]}",
            status="active",
            meta={},
        )
        session.add(venue)
        await session.flush()
        count_before = await session.scalar(
            select(func.count(AssessmentAssignment.id)).where(
                AssessmentAssignment.company_id == context.company.id
            )
        )
        with pytest.raises(OperationalWalkthroughNotFound):
            await AssessmentOperationalWalkthroughService(session).start(
                context.account.id,
                context.company.id,
                venue.id,
                context.version.id,
                NOW,
            )
        count_after = await session.scalar(
            select(func.count(AssessmentAssignment.id)).where(
                AssessmentAssignment.company_id == context.company.id
            )
        )
        assert count_after == count_before
        await session.rollback()
    await engine.dispose()
