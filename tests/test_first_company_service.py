"""PostgreSQL tests for atomic first Owner/Company onboarding."""

import asyncio
from datetime import datetime, timezone
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue
from app.internal.services.account_bootstrap_service import AccountBootstrapService
from app.internal.services.first_company_service import (
    CreateFirstCompany,
    FirstCompanyService,
    FirstCompanyUnavailable,
    OWNER_PERMISSION_CODES,
)


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def account(session: AsyncSession, name: str = "Synthetic Owner") -> Account:
    value = Account(
        id=uuid4(),
        display_name=name,
        password_hash="synthetic-hash",
        pin_hash=None,
        status="active",
        security_version=1,
        password_changed_at=NOW,
        last_login_at=None,
    )
    session.add(value)
    await session.flush()
    return value


def request(account_id, **changes):
    values = dict(
        account_id=account_id,
        expected_security_version=1,
        company_name=" Пилотная организация ",
        venue_name=None,
        timezone="Europe/Moscow",
        locale="ru-RU",
        now=NOW,
    )
    values.update(changes)
    return CreateFirstCompany(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize("venue_name", [None, " Первый ресторан "])
async def test_create_first_company_builds_exact_owner_aggregate(db_session, venue_name):
    owner = await account(db_session)
    result = await FirstCompanyService(
        db_session, code_factory=lambda _name, _attempt: f"pilot-{uuid4().hex[:12]}"
    ).create(request(owner.id, venue_name=venue_name))
    company = await db_session.get(Company, result.company_id)
    profile = await db_session.get(EmployeeProfile, result.employee_profile_id)
    position = await db_session.get(Position, result.position_id)
    access = await db_session.get(AccessProfile, result.access_profile_id)
    assignment = await db_session.get(EmployeeAssignment, result.employee_assignment_id)
    permissions = set(
        (
            await db_session.execute(
                select(AccessProfilePermission.permission_code).where(
                    AccessProfilePermission.access_profile_id == access.id
                )
            )
        ).scalars()
    )
    assert result.created is True
    assert company.owner_account_id == owner.id and company.name == "Пилотная организация"
    assert company.timezone == "Europe/Moscow" and company.locale == "ru-RU"
    assert profile.account_id == owner.id and profile.employment_status == "active"
    assert profile.full_name == owner.display_name and profile.phone is None
    assert position.code == access.code == "owner"
    assert position.default_access_profile_id == access.id
    assert access.maximum_scope == assignment.scope_type == "company"
    assert assignment.is_primary is True and assignment.status == "active"
    assert permissions == set(OWNER_PERMISSION_CODES)
    assert (result.venue_id is not None) is (venue_name is not None)
    assert await db_session.get(Venue, result.venue_id) if result.venue_id else True
    bootstrap = await AccountBootstrapService(db_session).get(owner.id, NOW)
    assert len(bootstrap.companies) == 1
    assert bootstrap.companies[0].company_id == company.id
    assert bootstrap.companies[0].relationship == "owner"


@pytest.mark.asyncio
async def test_repeat_is_controlled_idempotent_and_does_not_create_automatically(db_session):
    owner = await account(db_session)
    service = FirstCompanyService(db_session)
    before = await db_session.scalar(select(func.count()).select_from(Company))
    first = await service.create(request(owner.id))
    second = await service.create(request(owner.id, company_name="Ignored duplicate"))
    after = await db_session.scalar(select(func.count()).select_from(Company))
    assert after == before + 1
    assert first.created is True and second.created is False
    assert first.company_id == second.company_id


@pytest.mark.asyncio
async def test_duplicate_code_is_skipped_and_stale_security_is_rejected(db_session):
    existing_owner = await account(db_session, "Existing")
    existing = Company(
        id=uuid4(),
        owner_account_id=existing_owner.id,
        name="Existing",
        code="duplicate-code",
        timezone="Europe/Moscow",
        locale="ru-RU",
        status="active",
        meta={},
    )
    db_session.add(existing)
    await db_session.flush()
    new_owner = await account(db_session, "New")
    candidates = iter(["duplicate-code", "unique-code"])
    result = await FirstCompanyService(
        db_session, code_factory=lambda _name, _attempt: next(candidates)
    ).create(request(new_owner.id))
    assert result.company_code == "unique-code"
    stale_owner = await account(db_session, "Stale")
    with pytest.raises(FirstCompanyUnavailable):
        await FirstCompanyService(db_session).create(
            request(stale_owner.id, expected_security_version=2)
        )
    assert await db_session.scalar(
        select(func.count()).select_from(Company).where(
            Company.owner_account_id == stale_owner.id
        )
    ) == 0


@pytest.mark.asyncio
async def test_rollback_leaves_no_partial_aggregate(db_session):
    owner = await account(db_session)
    savepoint = await db_session.begin_nested()
    result = await FirstCompanyService(db_session).create(request(owner.id))
    await savepoint.rollback()
    assert await db_session.get(Company, result.company_id) is None
    for model in (EmployeeProfile, Position, AccessProfile, EmployeeAssignment, Venue):
        assert await db_session.scalar(
            select(func.count()).select_from(model).where(model.company_id == result.company_id)
        ) == 0


@pytest.mark.asyncio
async def test_ten_worker_concurrency_has_one_create_and_nine_idempotent_results():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    owner_id = uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        setup.add(
            Account(
                id=owner_id,
                display_name="Concurrent Owner",
                password_hash="synthetic-hash",
                pin_hash=None,
                status="active",
                security_version=1,
                password_changed_at=NOW,
                last_login_at=None,
            )
        )
        await setup.commit()

    async def worker(index: int):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await FirstCompanyService(session).create(
                request(owner_id, company_name=f"Concurrent {index}")
            )
            await session.commit()
            assert await session.scalar(select(1)) == 1
            return result

    results = await asyncio.gather(*(worker(index) for index in range(10)))
    assert sum(value.created for value in results) == 1
    assert len({value.company_id for value in results}) == 1
    async with AsyncSession(engine) as check:
        company_id = results[0].company_id
        assert await check.scalar(
            select(func.count()).select_from(Company).where(Company.owner_account_id == owner_id)
        ) == 1
        assert await check.scalar(
            select(func.count()).select_from(EmployeeAssignment).where(
                EmployeeAssignment.company_id == company_id
            )
        ) == 1
    await engine.dispose()
