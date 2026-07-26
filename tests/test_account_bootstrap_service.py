"""PostgreSQL integration coverage for the read-only Account bootstrap service."""

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infra.database.models.access_profile import AccessProfile
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.internal.services.account_bootstrap_service import (
    AccountBootstrapService,
    AccountBootstrapUnavailable,
)


NOW = datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        transaction = await session.begin()
        yield session
        await transaction.rollback()
    await engine.dispose()


async def _account(session, *, status="active", deleted=False):
    account = Account(
        id=uuid4(),
        display_name=f"Account {uuid4()}",
        status=status,
        security_version=1,
        deleted_at=NOW if deleted else None,
    )
    session.add(account)
    await session.flush()
    return account


async def _company(
    session,
    owner,
    *,
    name="Company",
    status="active",
    deleted=False,
):
    identifier = uuid4()
    company = Company(
        id=identifier,
        owner_account_id=owner.id,
        name=name,
        code=f"company-{identifier.hex}",
        timezone="Europe/Moscow",
        locale="ru-RU",
        status=status,
        deleted_at=NOW if deleted else None,
    )
    session.add(company)
    await session.flush()
    return company


async def _employee_membership(
    session,
    account,
    *,
    company=None,
    profile_status="active",
    profile_deleted=False,
    assignment_status="active",
    starts_at=None,
    ends_at=None,
    position_active=True,
    position_deleted=False,
    access_active=True,
    access_deleted=False,
    create_assignment=True,
):
    if company is None:
        owner = await _account(session)
        company = await _company(session, owner)
    profile = EmployeeProfile(
        id=uuid4(),
        company_id=company.id,
        account_id=account.id,
        full_name=f"Employee {uuid4()}",
        employment_status=profile_status,
        hired_at=NOW if profile_status == "active" else None,
        terminated_at=NOW if profile_status == "terminated" else None,
        deleted_at=NOW if profile_deleted else None,
    )
    session.add(profile)
    await session.flush()

    marker = uuid4().hex
    access = AccessProfile(
        id=uuid4(),
        company_id=company.id,
        name="Bootstrap access",
        code=f"bootstrap-access-{marker}",
        maximum_scope="company",
        is_active=access_active,
        deleted_at=NOW if access_deleted else None,
    )
    session.add(access)
    await session.flush()
    position = Position(
        id=uuid4(),
        company_id=company.id,
        name="Bootstrap position",
        code=f"bootstrap-position-{marker}",
        is_active=position_active,
        deleted_at=NOW if position_deleted else None,
    )
    session.add(position)
    await session.flush()

    assignment = None
    if create_assignment:
        assignment = EmployeeAssignment(
            id=uuid4(),
            company_id=company.id,
            employee_profile_id=profile.id,
            position_id=position.id,
            access_profile_id=access.id,
            scope_type="company",
            is_primary=assignment_status == "active",
            status=assignment_status,
            starts_at=starts_at or NOW - timedelta(days=1),
            ends_at=ends_at,
            revoked_at=NOW if assignment_status == "revoked" else None,
            revoked_by_account_id=(
                account.id if assignment_status == "revoked" else None
            ),
            revoke_reason="test" if assignment_status == "revoked" else None,
        )
        session.add(assignment)
        await session.flush()
    return SimpleNamespace(
        company=company,
        profile=profile,
        position=position,
        access=access,
        assignment=assignment,
    )


@pytest.mark.asyncio
async def test_active_owner_bootstrap(db_session):
    account = await _account(db_session)
    company = await _company(db_session, account, name="Owner Company")

    result = await AccountBootstrapService(db_session).get(account.id, NOW)

    assert result.account_id == account.id
    assert result.account_status == "active"
    assert result.security_version == 1
    assert result.companies == (
        result.companies[0],
    )
    assert result.companies[0].company_id == company.id
    assert result.companies[0].employee_profile_id is None
    assert result.companies[0].relationship == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "deleted"),
    [("suspended", False), ("disabled", False), ("active", True)],
)
async def test_account_must_be_active_and_not_deleted(db_session, status, deleted):
    account = await _account(db_session, status=status, deleted=deleted)
    with pytest.raises(AccountBootstrapUnavailable):
        await AccountBootstrapService(db_session).get(account.id, NOW)
    assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_account_id", ["not-a-uuid", 1, None])
async def test_account_id_runtime_validation_precedes_sql(invalid_account_id):
    class NoSql:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("SQL must not execute")

    with pytest.raises(ValueError, match="account_id"):
        await AccountBootstrapService(NoSql()).get(invalid_account_id, NOW)


@pytest.mark.asyncio
async def test_now_runtime_validation_precedes_sql():
    class NoSql:
        async def execute(self, *_args, **_kwargs):
            raise AssertionError("SQL must not execute")

    with pytest.raises(ValueError, match="timezone-aware"):
        await AccountBootstrapService(NoSql()).get(uuid4(), datetime.now())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "deleted", "owned_by_current"),
    [
        ("suspended", False, True),
        ("closed", False, True),
        ("active", True, True),
        ("active", False, False),
    ],
)
async def test_owner_company_must_be_eligible(
    db_session, status, deleted, owned_by_current
):
    account = await _account(db_session)
    owner = account if owned_by_current else await _account(db_session)
    await _company(db_session, owner, status=status, deleted=deleted)
    result = await AccountBootstrapService(db_session).get(account.id, NOW)
    assert result.companies == ()


@pytest.mark.asyncio
async def test_active_employee_bootstrap(db_session):
    account = await _account(db_session)
    graph = await _employee_membership(db_session, account)
    result = await AccountBootstrapService(db_session).get(account.id, NOW)
    assert [(item.company_id, item.relationship) for item in result.companies] == [
        (graph.company.id, "employee")
    ]
    assert result.companies[0].employee_profile_id == graph.profile.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile_status", "deleted"),
    [
        ("invited", False),
        ("suspended", False),
        ("terminated", False),
        ("active", True),
    ],
)
async def test_employee_profile_must_be_eligible(
    db_session, profile_status, deleted
):
    account = await _account(db_session)
    await _employee_membership(
        db_session,
        account,
        profile_status=profile_status,
        profile_deleted=deleted,
    )
    result = await AccountBootstrapService(db_session).get(account.id, NOW)
    assert result.companies == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "pending",
        "revoked",
        "future",
        "expired",
        "position_inactive",
        "position_deleted",
        "access_inactive",
        "access_deleted",
    ],
)
async def test_employee_assignment_graph_must_be_eligible(db_session, change):
    account = await _account(db_session)
    kwargs = {
        "create_assignment": change != "missing",
        "assignment_status": (
            change if change in {"pending", "revoked"} else "active"
        ),
        "starts_at": (
            NOW + timedelta(days=1)
            if change == "future"
            else NOW - timedelta(days=2)
        ),
        "ends_at": NOW - timedelta(days=1) if change == "expired" else None,
        "position_active": change != "position_inactive",
        "position_deleted": change == "position_deleted",
        "access_active": change != "access_inactive",
        "access_deleted": change == "access_deleted",
    }
    await _employee_membership(db_session, account, **kwargs)
    result = await AccountBootstrapService(db_session).get(account.id, NOW)
    assert result.companies == ()


@pytest.mark.asyncio
async def test_unrelated_employee_graph_is_not_visible(db_session):
    account = await _account(db_session)
    other = await _account(db_session)
    await _employee_membership(db_session, other)
    result = await AccountBootstrapService(db_session).get(account.id, NOW)
    assert result.companies == ()


@pytest.mark.asyncio
async def test_deduplication_and_deterministic_ordering(db_session):
    account = await _account(db_session)
    same_name_high = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    same_name_low = UUID("00000000-0000-0000-0000-000000000001")
    owner_high = await _company(db_session, account, name=" Same   Name ")
    owner_high.id = same_name_high
    await db_session.flush()
    owner_low = await _company(db_session, account, name="same name")
    owner_low.id = same_name_low
    await db_session.flush()
    employee_graph = await _employee_membership(
        db_session, account, company=owner_low
    )
    employee_graph.assignment.is_primary = False
    duplicate = EmployeeAssignment(
        id=uuid4(),
        company_id=owner_low.id,
        employee_profile_id=employee_graph.profile.id,
        position_id=employee_graph.position.id,
        access_profile_id=employee_graph.access.id,
        scope_type="company",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    db_session.add(duplicate)
    await db_session.flush()

    result = await AccountBootstrapService(db_session).get(account.id, NOW)

    assert [item.company_id for item in result.companies] == [
        same_name_low,
        same_name_high,
    ]
    assert len(result.companies) == 2
    assert all(item.relationship == "owner" for item in result.companies)
    assert all(item.employee_profile_id is None for item in result.companies)


@pytest.mark.asyncio
async def test_empty_membership(db_session):
    account = await _account(db_session)
    result = await AccountBootstrapService(db_session).get(account.id, NOW)
    assert result.companies == ()


@pytest.mark.asyncio
async def test_response_boundary_contains_only_contract_fields(db_session):
    account = await _account(db_session)
    await _company(db_session, account)
    result = await AccountBootstrapService(db_session).get(account.id, NOW)
    assert set(result.__dict__) == {
        "account_id",
        "account_status",
        "security_version",
        "companies",
    }
    assert set(result.companies[0].__dict__) == {
        "company_id",
        "company_name",
        "employee_profile_id",
        "relationship",
    }


@pytest.mark.asyncio
async def test_service_is_select_only_and_outer_session_remains_usable(db_session):
    account = await _account(db_session)
    await _company(db_session, account)

    class SelectOnlySpy:
        def __init__(self, delegate):
            self.delegate = delegate
            self.execute_calls = 0

        async def execute(self, statement):
            self.execute_calls += 1
            return await self.delegate.execute(statement)

        def __getattr__(self, name):
            if name in {
                "add",
                "add_all",
                "flush",
                "commit",
                "rollback",
                "begin",
                "begin_nested",
            }:
                raise AssertionError(f"{name} must not be used")
            return getattr(self.delegate, name)

    spy = SelectOnlySpy(db_session)
    result = await AccountBootstrapService(spy).get(account.id, NOW)
    assert result.companies
    assert spy.execute_calls == 3
    assert (await db_session.execute(select(1))).scalar_one() == 1
