"""PostgreSQL persistence regressions for weighted assessment results."""

from datetime import timedelta
import json
import os
from pathlib import Path
from types import MethodType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.routers.account_assessments import AssessmentWeightedV1Response
from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentMetricObservation,
    AssessmentTemplateVersion,
)
from app.internal.services.assessment_attempt_service import (
    AnswerInput,
    AssessmentAttemptService,
    ReplaceDraft,
)
from app.internal.services.assessment_management_service import (
    AssessmentManagementService,
    CreateAssignment,
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
from tests.test_account_organization_access_service import (
    NOW as ORGANIZATION_NOW,
    create_organization,
)


MANIFEST = (
    Path(__file__).parents[1]
    / "app/internal/data/assessment_template_import/manifests/cook-kln.json"
)
SUBMIT_AT = ORGANIZATION_NOW + timedelta(hours=1)


async def _create_committed_weighted_attempt(engine):
    """Create the complete aggregate through production application services."""

    async with AsyncSession(engine, expire_on_commit=False) as session:
        owner, company = await create_organization(session, "Weighted JSON")
        imported = await AssessmentTemplateImportService(session).apply(
            company.company_id,
            ReviewedManifest.parse(MANIFEST.read_bytes()),
            ORGANIZATION_NOW + timedelta(minutes=10),
        )
        version = await session.get(
            AssessmentTemplateVersion, imported.template_version_id
        )
        assert version is not None
        lifecycle = AssessmentTemplateService(session)
        await lifecycle.publish_methodology(
            PublishMethodology(
                version.methodology_id,
                ORGANIZATION_NOW + timedelta(minutes=11),
            )
        )
        await lifecycle.publish_template_version(
            PublishTemplateVersion(
                imported.template_id,
                imported.template_version_id,
                ORGANIZATION_NOW + timedelta(minutes=12),
            )
        )
        assignment = await AssessmentManagementService(session).create_assignment(
            CreateAssignment(
                owner.id,
                company.company_id,
                company.employee_profile_id,
                imported.template_version_id,
                None,
                SUBMIT_AT + timedelta(days=1),
                ORGANIZATION_NOW + timedelta(minutes=20),
            )
        )
        attempts = AssessmentAttemptService(session)
        document = await attempts.create_or_resume(
            owner.id,
            assignment["id"],
            ORGANIZATION_NOW + timedelta(minutes=21),
        )
        answers = [
            AnswerInput(item["id"], item["answer_type"], True)
            for section in document["document"]["sections"]
            for item in section["items"]
        ]
        saved = await attempts.replace_draft(
            ReplaceDraft(
                owner.id,
                document["id"],
                document["revision"],
                answers,
                ORGANIZATION_NOW + timedelta(minutes=22),
            )
        )
        assert saved["revision"] == 1
        await session.commit()
        return SimpleNamespace(
            account_id=owner.id,
            company_id=company.company_id,
            employee_profile_id=company.employee_profile_id,
            template_version_id=imported.template_version_id,
            assignment_id=assignment["id"],
            attempt_id=document["id"],
        )


@pytest.mark.asyncio
async def test_weighted_submit_persists_strict_json_and_is_idempotent():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    context = await _create_committed_weighted_attempt(engine)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await AssessmentAttemptService(session).submit(
            context.account_id, context.attempt_id, SUBMIT_AT
        )
        await session.commit()

    assert result["scoring_algorithm"] == "weighted_v1"
    assert len(result["sections"]) == 4
    assert all(
        isinstance(section["section_id"], str) and UUID(section["section_id"])
        for section in result["sections"]
    )
    assert json.loads(json.dumps(result)) == result
    validated = AssessmentWeightedV1Response.model_validate(result)
    assert validated.score_percent == result["score_percent"]

    async with AsyncSession(engine, expire_on_commit=False) as session:
        stored = await session.get(AssessmentAttempt, context.attempt_id)
        assert stored is not None and stored.status == "submitted"
        assert stored.result_json == result
        observation_count = await session.scalar(
            select(func.count())
            .select_from(AssessmentMetricObservation)
            .where(AssessmentMetricObservation.attempt_id == context.attempt_id)
        )
        assert observation_count is not None and observation_count > 0
        repeated = await AssessmentAttemptService(session).submit(
            context.account_id, context.attempt_id, SUBMIT_AT + timedelta(seconds=1)
        )
        await session.commit()
        assert repeated == result

    async with AsyncSession(engine) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AssessmentMetricObservation)
                .where(AssessmentMetricObservation.attempt_id == context.attempt_id)
            )
            == observation_count
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_unsupported_weighted_result_rolls_back_attempt_and_observations():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    context = await _create_committed_weighted_attempt(engine)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        observations_before = await session.scalar(
            select(func.count())
            .select_from(AssessmentMetricObservation)
            .where(AssessmentMetricObservation.attempt_id == context.attempt_id)
        )
        service = AssessmentAttemptService(session)
        production_weighted_result = service._weighted_result

        async def unsupported_result(self, *args, **kwargs):
            result = await production_weighted_result(*args, **kwargs)
            result["unsupported_test_value"] = uuid4()
            return result

        service._weighted_result = MethodType(unsupported_result, service)
        with pytest.raises(StatementError, match="UUID is not JSON serializable"):
            await service.submit(context.account_id, context.attempt_id, SUBMIT_AT)
        await session.rollback()
        assert await session.scalar(select(1)) == 1

    async with AsyncSession(engine) as session:
        attempt = await session.get(AssessmentAttempt, context.attempt_id)
        assignment = await session.get(AssessmentAssignment, context.assignment_id)
        assert attempt is not None and attempt.status == "draft"
        assert attempt.result_json is None and attempt.submitted_at is None
        assert assignment is not None and assignment.status == "in_progress"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AssessmentMetricObservation)
                .where(AssessmentMetricObservation.attempt_id == context.attempt_id)
            )
            == observations_before
        )
        assert await session.scalar(select(1)) == 1
    await engine.dispose()
