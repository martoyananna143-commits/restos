"""PostgreSQL integration tests for assessment management."""

import asyncio
from datetime import datetime, timedelta, timezone
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentAttemptAnswer,
)
from app.internal.services.assessment_management_service import (
    AssessmentManagementAlreadyCompleted,
    AssessmentManagementDuplicate,
    AssessmentManagementNotFound,
    AssessmentManagementPermissionDenied,
    AssessmentManagementService,
    CreateAssignment,
    StartManagerMeasurement,
)
from app.internal.services.assessment_attempt_service import (
    AnswerInput,
    AssessmentAttemptReadOnly,
    AssessmentAttemptService,
    ReplaceDraft,
)
from tests.test_assessment_attempt_service import seed_context


NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def command(context, *, due_at=None):
    return CreateAssignment(
        account_id=context.account.id,
        company_id=context.company.id,
        employee_profile_id=context.profile.id,
        template_version_id=context.version.id,
        venue_id=None,
        due_at=due_at,
        now=NOW,
    )


def measurement_command(context):
    return StartManagerMeasurement(
        account_id=context.account.id,
        company_id=context.company.id,
        subject_employee_profile_id=context.profile.id,
        template_version_id=context.version.id,
        venue_id=None,
        now=NOW,
    )


@pytest.mark.asyncio
async def test_manager_measurement_uses_subject_and_manager_owned_attempt():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context = await seed_context(session)
        context.assignment.status = "completed"
        context.assignment.completed_at = NOW
        await session.flush()
        result = await AssessmentManagementService(session).start_manager_measurement(
            measurement_command(context)
        )
        attempt = await session.get(AssessmentAttempt, result["id"])
        assignment = await session.get(AssessmentAssignment, result["assignment_id"])
        assert assignment.purpose == "manager_measurement"
        assert assignment.employee_profile_id == context.profile.id
        assert assignment.assigned_by_account_id == context.account.id
        assert attempt.account_id == context.account.id
        assert result["read_only"] is False
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_owner_directory_templates_and_safe_assignment_projection():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context = await seed_context(session)
        service = AssessmentManagementService(session)
        employees = await service.list_employees(
            context.account.id,
            context.company.id,
            NOW,
            q="Employ",
            limit=50,
            after=None,
        )
        templates = await service.list_templates(
            context.account.id, context.company.id, NOW
        )
        assignments = await service.list_assignments(
            context.account.id,
            context.company.id,
            NOW,
            status=None,
            limit=50,
            after=None,
        )
        assert employees == [
            {
                "employee_profile_id": context.profile.id,
                "display_name": "Employee",
                "position_title": "Employee",
                "status": "active",
            }
        ]
        assert templates[0]["template_version_id"] == context.version.id
        assert assignments[0]["id"] == context.assignment.id
        assert assignments[0]["progress"]["completion"] is None
        serialized = str(assignments).lower()
        for forbidden in (
            "value_json",
            "'answers'",
            "passing_value",
            "recommendation",
        ):
            assert forbidden not in serialized
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_operational_walkthrough_is_not_exposed_as_employee_assignment():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context = await seed_context(session)
        context.template.activity_type = "walkthrough"
        await session.flush()
        service = AssessmentManagementService(session)

        assert (
            await service.list_templates(context.account.id, context.company.id, NOW)
            == []
        )
        with pytest.raises(AssessmentManagementNotFound):
            await service.create_assignment(command(context))

        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_sets_account_audit_and_allows_repeat_after_terminal_states():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context = await seed_context(session)
        context.assignment.status = "completed"
        context.assignment.completed_at = NOW
        await session.flush()
        service = AssessmentManagementService(session)
        created = await service.create_assignment(
            command(context, due_at=NOW + timedelta(days=2))
        )
        row = await session.get(AssessmentAssignment, created["id"])
        assert row.assigned_by_account_id == context.account.id
        assert row.assigned_by_employee_profile_id == context.profile.id
        assert row.status == "assigned"
        assert row.purpose == "employee_evaluation"
        row.status = "revoked"
        row.revoked_at = NOW
        await session.flush()
        repeated = await service.create_assignment(command(context))
        assert repeated["id"] != created["id"]
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_sequential_duplicate_is_controlled_and_session_remains_usable():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context = await seed_context(session)
        service = AssessmentManagementService(session)
        with pytest.raises(AssessmentManagementDuplicate):
            await service.create_assignment(command(context))
        assert (await session.execute(select(1))).scalar_one() == 1
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_revoke_is_idempotent_and_completed_is_protected():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as session:
        context = await seed_context(session)
        service = AssessmentManagementService(session)
        first = await service.revoke_assignment(
            context.account.id, context.company.id, context.assignment.id, NOW
        )
        second = await service.revoke_assignment(
            context.account.id,
            context.company.id,
            context.assignment.id,
            NOW + timedelta(minutes=1),
        )
        assert first["status"] == second["status"] == "revoked"
        assert first["revoked_at"] == second["revoked_at"] == NOW
        context.assignment.status = "completed"
        context.assignment.revoked_at = None
        context.assignment.completed_at = NOW
        await session.flush()
        with pytest.raises(AssessmentManagementAlreadyCompleted):
            await service.revoke_assignment(
                context.account.id,
                context.company.id,
                context.assignment.id,
                NOW,
            )
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_ten_worker_concurrent_create_has_one_winner():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        context = await seed_context(setup)
        context.assignment.status = "completed"
        context.assignment.completed_at = NOW
        await setup.commit()
        values = command(context)

    async with AsyncSession(engine) as before:
        attempt_count_before = (
            await before.execute(select(func.count()).select_from(AssessmentAttempt))
        ).scalar_one()
        answer_count_before = (
            await before.execute(
                select(func.count()).select_from(AssessmentAttemptAnswer)
            )
        ).scalar_one()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def worker():
        nonlocal ready
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with ready_lock:
                ready += 1
                if ready == 10:
                    start.set()
            await start.wait()
            try:
                result = await AssessmentManagementService(session).create_assignment(
                    values
                )
                await session.commit()
                return "success", result["id"]
            except AssessmentManagementDuplicate:
                await session.rollback()
                assert (await session.execute(select(1))).scalar_one() == 1
                return "duplicate", None

    results = await asyncio.gather(*(worker() for _ in range(10)))
    assert [value[0] for value in results].count("success") == 1
    assert [value[0] for value in results].count("duplicate") == 9
    winner_id = next(value[1] for value in results if value[0] == "success")
    async with AsyncSession(engine) as verify:
        count = (
            await verify.execute(
                select(func.count())
                .select_from(AssessmentAssignment)
                .where(
                    AssessmentAssignment.company_id == values.company_id,
                    AssessmentAssignment.employee_profile_id
                    == values.employee_profile_id,
                    AssessmentAssignment.template_version_id
                    == values.template_version_id,
                    AssessmentAssignment.status.in_(("assigned", "in_progress")),
                )
            )
        ).scalar_one()
        assert count == 1
        attempt_count_after = (
            await verify.execute(select(func.count()).select_from(AssessmentAttempt))
        ).scalar_one()
        answer_count_after = (
            await verify.execute(
                select(func.count()).select_from(AssessmentAttemptAnswer)
            )
        ).scalar_one()
        assert attempt_count_after == attempt_count_before
        assert answer_count_after == answer_count_before
        winner = await verify.get(AssessmentAssignment, winner_id)
        assert winner is not None
        assert winner.company_id == values.company_id
        assert winner.employee_profile_id == values.employee_profile_id
        assert winner.template_version_id == values.template_version_id
        assert winner.assigned_by_account_id == values.account_id
        assert winner.status == "assigned"
        scoped_attempt_ids = select(AssessmentAttempt.id).where(
            AssessmentAttempt.assignment_id == winner_id
        )
        scoped_attempt_count = (
            await verify.execute(
                select(func.count())
                .select_from(AssessmentAttempt)
                .where(AssessmentAttempt.assignment_id == winner_id)
            )
        ).scalar_one()
        scoped_answer_count = (
            await verify.execute(
                select(func.count())
                .select_from(AssessmentAttemptAnswer)
                .where(AssessmentAttemptAnswer.attempt_id.in_(scoped_attempt_ids))
            )
        ).scalar_one()
        assert scoped_attempt_count == 0
        assert scoped_answer_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_ordinary_employee_is_denied(monkeypatch):
    class Access:
        def __init__(self, _session):
            pass

        async def can_in_company(self, *_args):
            return False

        async def list_accessible_venue_ids(self, *_args):
            return set()

    monkeypatch.setattr(
        "app.internal.services.assessment_management_service.AccessDecisionService",
        Access,
    )
    with pytest.raises(AssessmentManagementPermissionDenied):
        await AssessmentManagementService(None)._require_read(
            context_id := __import__("uuid").uuid4(),
            __import__("uuid").uuid4(),
            NOW,
        )
    assert context_id is not None


@pytest.mark.asyncio
async def test_manage_permission_implies_read_but_read_does_not_imply_manage(
    monkeypatch,
):
    class Access:
        def __init__(self, _session):
            pass

        async def can_in_company(self, _account, _company, permission, _now):
            return permission == "assessment.assignment.manage"

        async def list_accessible_venue_ids(self, *_args):
            return set()

    monkeypatch.setattr(
        "app.internal.services.assessment_management_service.AccessDecisionService",
        Access,
    )
    service = AssessmentManagementService(None)
    await service._require_read(
        __import__("uuid").uuid4(), __import__("uuid").uuid4(), NOW
    )
    await service._require_manage(
        __import__("uuid").uuid4(), __import__("uuid").uuid4(), NOW
    )

    class ReadOnlyAccess(Access):
        async def can_in_company(self, _account, _company, permission, _now):
            return permission == "assessment.assignment.read"

    monkeypatch.setattr(
        "app.internal.services.assessment_management_service.AccessDecisionService",
        ReadOnlyAccess,
    )
    await service._require_read(
        __import__("uuid").uuid4(), __import__("uuid").uuid4(), NOW
    )
    with pytest.raises(AssessmentManagementPermissionDenied):
        await service._require_manage(
            __import__("uuid").uuid4(), __import__("uuid").uuid4(), NOW
        )


@pytest.mark.asyncio
async def test_ten_worker_revoke_is_idempotent_without_duplicate_mutation():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        context = await seed_context(setup)
        values = (
            context.account.id,
            context.company.id,
            context.assignment.id,
        )
        await setup.commit()
    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def worker():
        nonlocal ready
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with ready_lock:
                ready += 1
                if ready == 10:
                    start.set()
            await start.wait()
            result = await AssessmentManagementService(session).revoke_assignment(
                *values, NOW
            )
            await session.commit()
            return result["revoked_at"]

    revoked_at_values = await asyncio.gather(*(worker() for _ in range(10)))
    assert revoked_at_values == [NOW] * 10
    async with AsyncSession(engine) as verify:
        assignment = await verify.get(AssessmentAssignment, values[2])
        assert assignment.status == "revoked"
        assert assignment.revoked_at == NOW
        assert (await verify.execute(select(1))).scalar_one() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_revoke_race_has_one_valid_terminal_outcome():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        context = await seed_context(setup)
        attempt_service = AssessmentAttemptService(setup)
        attempt = await attempt_service.create_or_resume(
            context.account.id, context.assignment.id, NOW
        )
        await attempt_service.replace_draft(
            ReplaceDraft(
                context.account.id,
                attempt["id"],
                0,
                [AnswerInput(context.required.id, "boolean", True)],
                NOW,
            )
        )
        values = (
            context.account.id,
            context.company.id,
            context.assignment.id,
            attempt["id"],
        )
        await setup.commit()
    start = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def admitted():
        nonlocal ready
        async with ready_lock:
            ready += 1
            if ready == 2:
                start.set()
        await start.wait()

    async def submit_worker():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await admitted()
            try:
                await AssessmentAttemptService(session).submit(
                    values[0], values[3], NOW
                )
                await session.commit()
                return "submitted"
            except AssessmentAttemptReadOnly:
                await session.rollback()
                assert (await session.execute(select(1))).scalar_one() == 1
                return "read_only"

    async def revoke_worker():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await admitted()
            try:
                await AssessmentManagementService(session).revoke_assignment(
                    values[0], values[1], values[2], NOW
                )
                await session.commit()
                return "revoked"
            except AssessmentManagementAlreadyCompleted:
                await session.rollback()
                assert (await session.execute(select(1))).scalar_one() == 1
                return "already_completed"

    outcomes = await asyncio.gather(submit_worker(), revoke_worker())
    assert outcomes in (
        ["submitted", "already_completed"],
        ["read_only", "revoked"],
    )
    async with AsyncSession(engine) as verify:
        assignment = await verify.get(AssessmentAssignment, values[2])
        attempt_row = await verify.get(AssessmentAttempt, values[3])
        assert (assignment.status, attempt_row.status) in {
            ("completed", "submitted"),
            ("revoked", "draft"),
        }
        assert (await verify.execute(select(1))).scalar_one() == 1
    await engine.dispose()
