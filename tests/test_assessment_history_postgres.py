"""PostgreSQL history, immutable result and cursor pagination regressions."""

from datetime import timedelta
import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models import AssessmentAttempt
from app.internal.services.assessment_attempt_service import (
    AnswerInput,
    AssessmentAttemptService,
    ReplaceDraft,
)
from app.internal.services.assessment_history_service import (
    AssessmentHistoryNotFound,
    AssessmentHistoryService,
    HistoryPageQuery,
)
from app.internal.services.assessment_management_service import (
    AssessmentManagementService,
    CreateAssignment,
)
from tests.test_weighted_attempt_json_persistence import (
    SUBMIT_AT,
    _create_committed_weighted_attempt,
)


async def _submit_attempt(session, account_id, attempt_id, submitted_at):
    result = await AssessmentAttemptService(session).submit(
        account_id, attempt_id, submitted_at
    )
    assert result["scoring_algorithm"] == "weighted_v1"
    return result


async def _create_second_attempt(session, context):
    assignment = await AssessmentManagementService(session).create_assignment(
        CreateAssignment(
            context.account_id,
            context.company_id,
            context.employee_profile_id,
            context.template_version_id,
            None,
            SUBMIT_AT + timedelta(days=2),
            SUBMIT_AT + timedelta(minutes=1),
        )
    )
    service = AssessmentAttemptService(session)
    document = await service.create_or_resume(
        context.account_id,
        assignment["id"],
        SUBMIT_AT + timedelta(minutes=2),
    )
    answers = [
        AnswerInput(item["id"], item["answer_type"], True)
        for section in document["document"]["sections"]
        for item in section["items"]
    ]
    await service.replace_draft(
        ReplaceDraft(
            context.account_id,
            document["id"],
            document["revision"],
            answers,
            SUBMIT_AT + timedelta(minutes=3),
        )
    )
    await _submit_attempt(
        session,
        context.account_id,
        document["id"],
        SUBMIT_AT + timedelta(hours=1),
    )
    return document["id"]


@pytest.mark.asyncio
async def test_history_pages_are_stable_and_result_is_immutable_and_authorized():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    context = await _create_committed_weighted_attempt(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        first_result = await _submit_attempt(
            session, context.account_id, context.attempt_id, SUBMIT_AT
        )
        second_attempt_id = await _create_second_attempt(session, context)
        await session.commit()

    now = SUBMIT_AT + timedelta(days=3)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = AssessmentHistoryService(session)
        first_page = await service.history(
            HistoryPageQuery(
                account_id=context.account_id,
                company_id=context.company_id,
                now=now,
                limit=1,
            )
        )
        assert [item["attempt_id"] for item in first_page["items"]] == [
            second_attempt_id
        ]
        assert first_page["next_cursor"]
        second_page = await service.history(
            HistoryPageQuery(
                account_id=context.account_id,
                company_id=context.company_id,
                now=now,
                limit=1,
                cursor=first_page["next_cursor"],
            )
        )
        assert [item["attempt_id"] for item in second_page["items"]] == [
            context.attempt_id
        ]
        assert second_page["next_cursor"] is None
        assert set(item["attempt_id"] for item in first_page["items"]).isdisjoint(
            item["attempt_id"] for item in second_page["items"]
        )

        projection = await service.result_projection(
            context.account_id,
            context.company_id,
            context.attempt_id,
            now,
        )
        assert projection["score_percent"] == first_result["score_percent"]
        assert projection["score_display"].endswith("%")
        assert projection["sections"]
        assert all(
            "section_id" not in section and "section_code" not in section
            for section in projection["sections"]
        )
        assert all(
            "item_id" not in item
            for section in projection["sections"]
            for item in section["items"]
        )

        stored = await session.get(AssessmentAttempt, context.attempt_id)
        assert stored is not None and stored.result_json == first_result
        assert await session.scalar(select(1)) == 1

        with pytest.raises(AssessmentHistoryNotFound):
            await service.result_projection(
                uuid4(),
                context.company_id,
                context.attempt_id,
                now,
            )
        assert await session.scalar(select(1)) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_custom_history_period_uses_local_submitted_date_before_pagination():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    context = await _create_committed_weighted_attempt(engine)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await _submit_attempt(
            session, context.account_id, context.attempt_id, SUBMIT_AT
        )
        await session.commit()
    local_date = (SUBMIT_AT + timedelta(hours=3)).date()
    async with AsyncSession(engine) as session:
        page = await AssessmentHistoryService(session).history(
            HistoryPageQuery(
                account_id=context.account_id,
                company_id=context.company_id,
                now=SUBMIT_AT + timedelta(days=1),
                period="custom",
                date_from=local_date,
                date_to=local_date,
                limit=30,
            )
        )
        assert [item["attempt_id"] for item in page["items"]] == [context.attempt_id]
    await engine.dispose()
