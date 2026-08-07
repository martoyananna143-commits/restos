"""Validation and PostgreSQL integration tests for assessment attempts."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models import (
    AccessProfile,
    Account,
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentMethodology,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
    Company,
    EmployeeAssignment,
    EmployeeProfile,
    Position,
)
from app.internal.services.assessment_attempt_service import (
    AnswerInput,
    AssessmentAttemptInvalid,
    AssessmentAttemptIncomplete,
    AssessmentAttemptNotFound,
    AssessmentAttemptRevisionConflict,
    AssessmentAttemptService,
    ReplaceDraft,
)


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def service():
    return AssessmentAttemptService(None)  # value normalization does not access SQL


@pytest.mark.parametrize(
    ("answer_type", "value", "expected"),
    [
        ("boolean", True, True),
        ("integer", 12, 12),
        ("decimal", Decimal("1.25"), "1.25"),
        ("score", 7, "7"),
        ("text", "  answer  ", "answer"),
        ("date", "2026-08-07", "2026-08-07"),
        ("time", "12:30:00", "12:30:00"),
    ],
)
def test_normalizes_scalar_answer_types(answer_type, value, expected):
    assert service()._normalize_value(answer_type, value, set()) == expected


def test_choice_answers_require_owned_unique_options():
    first, second = uuid4(), uuid4()
    current = service()
    assert current._normalize_value("single_choice", first, {first}) == str(first)
    assert current._normalize_value("multi_choice", [first, second], {first, second}) == [str(first), str(second)]
    with pytest.raises(AssessmentAttemptInvalid):
        current._normalize_value("multi_choice", [first, first], {first})
    with pytest.raises(AssessmentAttemptInvalid):
        current._normalize_value("single_choice", second, {first})


@pytest.mark.parametrize(
    ("answer_type", "value"),
    [
        ("boolean", 1),
        ("integer", True),
        ("decimal", float("nan")),
        ("score", float("inf")),
        ("text", "x" * 10_001),
        ("date", "07.08.2026"),
        ("time", "noon"),
    ],
)
def test_rejects_ambiguous_or_unbounded_values(answer_type, value):
    with pytest.raises(AssessmentAttemptInvalid):
        service()._normalize_value(answer_type, value, set())


@pytest.mark.parametrize("value", [None, "", []])
def test_empty_optional_value_is_omitted(value):
    assert service()._normalize_value("text", value, set()) is None


async def seed_context(session: AsyncSession):
    suffix = uuid4().hex[:12]
    account = Account(display_name="Employee", status="active", security_version=1)
    session.add(account)
    await session.flush()
    company = Company(
        owner_account_id=account.id, name="Pilot", code=f"pilot-{suffix}",
        timezone="UTC", locale="ru-RU", status="active",
    )
    session.add(company)
    await session.flush()
    profile = EmployeeProfile(
        company_id=company.id, account_id=account.id, full_name="Employee",
        employment_status="active", meta={},
    )
    access = AccessProfile(
        company_id=company.id, name="Employee", code=f"employee-{suffix}",
        maximum_scope="self", is_system=False, is_active=True, version=1,
    )
    session.add_all([profile, access])
    await session.flush()
    position = Position(
        company_id=company.id, name="Employee", code=f"position-{suffix}",
        default_access_profile_id=access.id, is_active=True, sort_order=0,
    )
    session.add(position)
    await session.flush()
    membership = EmployeeAssignment(
        company_id=company.id, employee_profile_id=profile.id,
        position_id=position.id, access_profile_id=access.id,
        scope_type="self", is_primary=True, status="active", starts_at=NOW,
    )
    methodology = AssessmentMethodology(
        owner_type="company", company_id=company.id, code=f"method-{suffix}",
        title="Method", body="Employee-safe method", version=1,
        status="published", published_at=NOW,
    )
    template = AssessmentTemplate(
        scope="company", company_id=company.id, code=f"template-{suffix}",
        name="Pilot assessment", activity_type="evaluation", status="active",
    )
    session.add_all([membership, methodology, template])
    await session.flush()
    version = AssessmentTemplateVersion(
        template_id=template.id, version=1, status="published",
        methodology_id=methodology.id, published_at=NOW,
    )
    session.add(version)
    await session.flush()
    section = AssessmentTemplateSection(
        template_version_id=version.id, code=f"section-{suffix}", title="Section",
        section_kind="section", sort_order=0,
    )
    session.add(section)
    await session.flush()
    required = AssessmentTemplateItem(
        template_version_id=version.id, section_id=section.id,
        code=f"required-{suffix}", prompt="Required?", response_type="boolean",
        is_required=True, sort_order=0, evidence_mode="none",
        criticality="normal", config={},
    )
    optional = AssessmentTemplateItem(
        template_version_id=version.id, section_id=section.id,
        code=f"optional-{suffix}", prompt="Comment", response_type="text",
        is_required=False, sort_order=1, evidence_mode="none",
        criticality="normal", config={"placeholder": "Optional"},
    )
    session.add_all([required, optional])
    await session.flush()
    assignment = AssessmentAssignment(
        company_id=company.id, employee_profile_id=profile.id,
        template_version_id=version.id, status="assigned", assigned_at=NOW,
        due_at=NOW + timedelta(days=7),
    )
    session.add(assignment)
    await session.flush()
    return SimpleNamespace(
        account=account, company=company, profile=profile, version=version,
        required=required, optional=optional, assignment=assignment,
    )


@pytest_asyncio.fixture
async def db_context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    context = await seed_context(session)
    try:
        yield session, context
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_replace_conflict_submit_and_idempotency(db_context):
    session, context = db_context
    service = AssessmentAttemptService(session)
    created = await service.create_or_resume(context.account.id, context.assignment.id, NOW)
    assert created["revision"] == 0
    assert (await service.create_or_resume(context.account.id, context.assignment.id, NOW))["id"] == created["id"]
    with pytest.raises(AssessmentAttemptIncomplete):
        await service.submit(context.account.id, created["id"], NOW)
    saved = await service.replace_draft(ReplaceDraft(
        context.account.id, created["id"], 0,
        [AnswerInput(context.required.id, "boolean", True), AnswerInput(context.optional.id, "text", " note ")],
        NOW,
    ))
    assert saved["revision"] == 1
    assert len(saved["answers"]) == 2
    with pytest.raises(AssessmentAttemptRevisionConflict) as conflict:
        await service.replace_draft(ReplaceDraft(context.account.id, created["id"], 0, [], NOW))
    assert conflict.value.current_revision == 1
    assert len(conflict.value.answers) == 2
    replaced = await service.replace_draft(ReplaceDraft(
        context.account.id, created["id"], 1,
        [AnswerInput(context.required.id, "boolean", False)], NOW,
    ))
    assert replaced["revision"] == 2
    assert len(replaced["answers"]) == 1
    receipt = await service.submit(context.account.id, created["id"], NOW)
    assert receipt == await service.submit(context.account.id, created["id"], NOW)
    assert receipt == {
        "scoring_algorithm": "completion_v1", "submitted_at": NOW.isoformat(),
        "answered_count": 1, "required_count": 1, "total_count": 2,
    }
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_assignment_validation_uses_version_owning_template(db_context):
    session, context = db_context
    service = AssessmentAttemptService(session)
    await service._validate_assignment_template(context.assignment)
    suffix = uuid4().hex[:12]
    foreign_company = Company(
        owner_account_id=context.account.id, name="Foreign company",
        code=f"foreign-company-{suffix}", timezone="UTC", locale="ru-RU",
        status="active",
    )
    session.add(foreign_company)
    await session.flush()
    foreign_template = AssessmentTemplate(
        scope="company", company_id=foreign_company.id,
        code=f"foreign-template-{suffix}", name="Foreign",
        activity_type="evaluation", status="active",
    )
    session.add(foreign_template)
    await session.flush()
    foreign_version = AssessmentTemplateVersion(
        template_id=foreign_template.id, version=1, status="published",
        methodology_id=context.version.methodology_id, published_at=NOW,
    )
    session.add(foreign_version)
    await session.flush()
    mismatched_assignment = AssessmentAssignment(
        company_id=context.company.id,
        employee_profile_id=context.profile.id,
        template_version_id=foreign_version.id,
        status="assigned",
        assigned_at=NOW,
        due_at=NOW + timedelta(days=7),
    )
    session.add(mismatched_assignment)
    await session.flush()
    with pytest.raises(AssessmentAttemptNotFound):
        await service._validate_assignment_template(mismatched_assignment)
    await service._validate_assignment_template(context.assignment)
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_concurrent_create_resume_has_one_attempt():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        context = await seed_context(setup)
        account_id, assignment_id = context.account.id, context.assignment.id
        await setup.commit()

    async def worker():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            value = await AssessmentAttemptService(session).create_or_resume(account_id, assignment_id, NOW)
            await session.commit()
            return value["id"]

    ids = await asyncio.gather(*(worker() for _ in range(10)))
    assert len(set(ids)) == 1
    async with AsyncSession(engine) as verify:
        count = (await verify.execute(select(func.count()).select_from(AssessmentAttempt).where(
            AssessmentAttempt.assignment_id == assignment_id
        ))).scalar_one()
        assert count == 1
    await engine.dispose()


async def committed_attempt(engine, *, with_required_answer=False):
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        context = await seed_context(setup)
        service = AssessmentAttemptService(setup)
        attempt = await service.create_or_resume(
            context.account.id, context.assignment.id, NOW
        )
        if with_required_answer:
            attempt = await service.replace_draft(ReplaceDraft(
                context.account.id, attempt["id"], 0,
                [AnswerInput(context.required.id, "boolean", True)], NOW,
            ))
        values = SimpleNamespace(
            account_id=context.account.id,
            assignment_id=context.assignment.id,
            attempt_id=attempt["id"],
            required_id=context.required.id,
            optional_id=context.optional.id,
            revision=attempt["revision"],
        )
        await setup.commit()
        return values


@pytest.mark.asyncio
async def test_ten_worker_same_revision_autosave_has_one_complete_winner():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    context = await committed_attempt(engine)
    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def worker(index):
        nonlocal ready
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with ready_lock:
                ready += 1
                if ready == 10:
                    start.set()
            await start.wait()
            try:
                value = await AssessmentAttemptService(session).replace_draft(
                    ReplaceDraft(
                        context.account_id, context.attempt_id, context.revision,
                        [
                            AnswerInput(context.required_id, "boolean", index % 2 == 0),
                            AnswerInput(context.optional_id, "text", f"tree-{index}"),
                        ],
                        NOW + timedelta(seconds=index),
                    )
                )
                await session.commit()
                return ("success", index, value)
            except AssessmentAttemptRevisionConflict as error:
                await session.rollback()
                assert (await session.execute(select(1))).scalar_one() == 1
                return ("conflict", index, error)

    results = await asyncio.gather(*(worker(index) for index in range(10)))
    successes = [result for result in results if result[0] == "success"]
    conflicts = [result for result in results if result[0] == "conflict"]
    assert len(successes) == 1
    assert len(conflicts) == 9
    winner = successes[0]
    async with AsyncSession(engine) as verify:
        loaded = await AssessmentAttemptService(verify).read_attempt(
            context.account_id, context.attempt_id, NOW
        )
        assert loaded["revision"] == 1
        assert len(loaded["answers"]) == 2
        answer_by_item = {answer["item_id"]: answer["value"] for answer in loaded["answers"]}
        assert answer_by_item[context.optional_id] == f"tree-{winner[1]}"
        assert answer_by_item[context.required_id] is (winner[1] % 2 == 0)
    await engine.dispose()


@pytest.mark.asyncio
async def test_independent_attempts_save_without_cross_blocking():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    first = await committed_attempt(engine)
    second = await committed_attempt(engine)

    async def save(context, value):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await AssessmentAttemptService(session).replace_draft(
                ReplaceDraft(
                    context.account_id, context.attempt_id, 0,
                    [AnswerInput(context.required_id, "boolean", value)], NOW,
                )
            )
            await session.commit()
            return result

    first_result, second_result = await asyncio.gather(
        save(first, True), save(second, False)
    )
    assert first_result["revision"] == second_result["revision"] == 1
    assert first_result["answers"][0]["value"] is True
    assert second_result["answers"][0]["value"] is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_submit_is_idempotent_and_has_one_result():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    context = await committed_attempt(engine, with_required_answer=True)
    start = asyncio.Event()
    ready = 0
    lock = asyncio.Lock()

    async def submit():
        nonlocal ready
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with lock:
                ready += 1
                if ready == 10:
                    start.set()
            await start.wait()
            result = await AssessmentAttemptService(session).submit(
                context.account_id, context.attempt_id, NOW
            )
            await session.commit()
            return result

    results = await asyncio.gather(*(submit() for _ in range(10)))
    assert all(result == results[0] for result in results)
    assert results[0]["scoring_algorithm"] == "completion_v1"
    async with AsyncSession(engine) as verify:
        attempt = await verify.get(AssessmentAttempt, context.attempt_id)
        assignment = await verify.get(AssessmentAssignment, context.assignment_id)
        assert attempt.status == "submitted"
        assert assignment.status == "completed"
        assert attempt.result_json == results[0]
    await engine.dispose()
