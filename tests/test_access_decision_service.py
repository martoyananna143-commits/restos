"""PostgreSQL integration tests for additive access decisions."""

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue
from app.internal.services.access_decision_service import AccessDecisionService


NOW = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def access_context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    owner = Account(id=uuid4(), display_name="Owner", status="active")
    employee_account = Account(
        id=uuid4(), display_name="Employee", status="active"
    )
    other_owner = Account(id=uuid4(), display_name="Other owner", status="active")
    session.add_all([owner, employee_account, other_owner])
    await session.flush()

    company = Company(
        id=uuid4(),
        owner_account_id=owner.id,
        name="Company",
        code=f"company-{uuid4().hex[:8]}",
        timezone="UTC",
        locale="ru-RU",
        status="active",
    )
    other_company = Company(
        id=uuid4(),
        owner_account_id=other_owner.id,
        name="Other company",
        code=f"other-{uuid4().hex[:8]}",
        timezone="UTC",
        locale="ru-RU",
        status="active",
    )
    session.add_all([company, other_company])
    await session.flush()

    profile = EmployeeProfile(
        id=uuid4(),
        company_id=company.id,
        account_id=employee_account.id,
        full_name="Current employee",
        employment_status="active",
    )
    target_profile = EmployeeProfile(
        id=uuid4(),
        company_id=company.id,
        full_name="Target employee",
        employment_status="active",
    )
    other_profile = EmployeeProfile(
        id=uuid4(),
        company_id=other_company.id,
        full_name="Other employee",
        employment_status="active",
    )
    session.add_all([profile, target_profile, other_profile])
    await session.flush()

    access_profile = AccessProfile(
        id=uuid4(),
        company_id=company.id,
        name="Access",
        code=f"access-{uuid4().hex[:8]}",
        maximum_scope="company",
        is_system=False,
        is_active=True,
        version=1,
    )
    limited_profile = AccessProfile(
        id=uuid4(),
        company_id=company.id,
        name="Limited",
        code=f"limited-{uuid4().hex[:8]}",
        maximum_scope="self",
        is_system=False,
        is_active=True,
        version=1,
    )
    other_access_profile = AccessProfile(
        id=uuid4(),
        company_id=other_company.id,
        name="Other access",
        code=f"other-access-{uuid4().hex[:8]}",
        maximum_scope="company",
        is_system=False,
        is_active=True,
        version=1,
    )
    session.add_all([access_profile, limited_profile, other_access_profile])
    await session.flush()
    session.add_all(
        [
            AccessProfilePermission(
                access_profile_id=access_profile.id,
                permission_code="employee.view",
            ),
            AccessProfilePermission(
                access_profile_id=access_profile.id,
                permission_code="venue.view",
            ),
            AccessProfilePermission(
                access_profile_id=limited_profile.id,
                permission_code="limited.view",
            ),
        ]
    )

    position = Position(
        id=uuid4(),
        company_id=company.id,
        name="Position",
        code=f"position-{uuid4().hex[:8]}",
        is_active=True,
        sort_order=0,
    )
    other_position = Position(
        id=uuid4(),
        company_id=other_company.id,
        name="Other position",
        code=f"other-position-{uuid4().hex[:8]}",
        is_active=True,
        sort_order=0,
    )
    session.add_all([position, other_position])
    await session.flush()

    venue = Venue(
        id=uuid4(),
        company_id=company.id,
        name="Venue",
        code=f"venue-{uuid4().hex[:8]}",
        status="active",
    )
    second_venue = Venue(
        id=uuid4(),
        company_id=company.id,
        name="Second venue",
        code=f"second-{uuid4().hex[:8]}",
        status="temporarily_closed",
    )
    closed_venue = Venue(
        id=uuid4(),
        company_id=company.id,
        name="Closed venue",
        code=f"closed-{uuid4().hex[:8]}",
        status="closed",
    )
    deleted_venue = Venue(
        id=uuid4(),
        company_id=company.id,
        name="Deleted venue",
        code=f"deleted-{uuid4().hex[:8]}",
        status="active",
        deleted_at=NOW,
    )
    other_venue = Venue(
        id=uuid4(),
        company_id=other_company.id,
        name="Other venue",
        code=f"other-venue-{uuid4().hex[:8]}",
        status="active",
    )
    session.add_all(
        [venue, second_venue, closed_venue, deleted_venue, other_venue]
    )
    await session.flush()

    assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=company.id,
        employee_profile_id=profile.id,
        position_id=position.id,
        access_profile_id=access_profile.id,
        scope_type="self",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    target_assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=company.id,
        employee_profile_id=target_profile.id,
        position_id=position.id,
        access_profile_id=access_profile.id,
        scope_type="self",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    limited_assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=company.id,
        employee_profile_id=profile.id,
        position_id=position.id,
        access_profile_id=limited_profile.id,
        scope_type="company",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    session.add_all([assignment, target_assignment, limited_assignment])
    await session.flush()
    session.add_all(
        [
            AssignmentVenue(
                assignment_id=assignment.id,
                venue_id=venue.id,
                company_id=company.id,
            ),
            AssignmentScopeVenue(
                assignment_id=assignment.id,
                venue_id=second_venue.id,
                company_id=company.id,
            ),
            AssignmentVenue(
                assignment_id=target_assignment.id,
                venue_id=venue.id,
                company_id=company.id,
            ),
        ]
    )
    await session.flush()

    context = SimpleNamespace(
        session=session,
        service=AccessDecisionService(session),
        owner=owner,
        employee_account=employee_account,
        company=company,
        other_company=other_company,
        profile=profile,
        target_profile=target_profile,
        other_profile=other_profile,
        access_profile=access_profile,
        limited_profile=limited_profile,
        position=position,
        assignment=assignment,
        limited_assignment=limited_assignment,
        venue=venue,
        second_venue=second_venue,
        closed_venue=closed_venue,
        deleted_venue=deleted_venue,
        other_venue=other_venue,
    )
    try:
        yield context
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_company_boundaries(access_context):
    ctx = access_context
    assert await ctx.service.can_in_company(
        ctx.owner.id, ctx.company.id, "anything.manage", NOW
    )
    assert not await ctx.service.can_in_company(
        ctx.owner.id, ctx.other_company.id, "anything.manage", NOW
    )

    for status in ("suspended", "closed"):
        ctx.company.status = status
        await ctx.session.flush()
        assert not await ctx.service.can_in_company(
            ctx.owner.id, ctx.company.id, "anything.manage", NOW
        )
    ctx.company.status = "active"
    ctx.company.deleted_at = NOW
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.owner.id, ctx.company.id, "anything.manage", NOW
    )


@pytest.mark.asyncio
async def test_exact_permission_and_eligibility_filters(access_context):
    ctx = access_context
    ctx.assignment.scope_type = "company"
    await ctx.session.flush()
    assert await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.manage", NOW
    )
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.viewer", NOW
    )

    for status in ("invited", "suspended"):
        ctx.profile.employment_status = status
        await ctx.session.flush()
        assert not await ctx.service.can_in_company(
            ctx.employee_account.id, ctx.company.id, "employee.view", NOW
        )
    ctx.profile.employment_status = "terminated"
    ctx.profile.terminated_at = NOW
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.profile.employment_status = "active"
    ctx.profile.terminated_at = None

    ctx.assignment.status = "pending"
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.assignment.status = "ended"
    ctx.assignment.ends_at = NOW + timedelta(hours=1)
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.assignment.status = "revoked"
    ctx.assignment.revoked_at = NOW
    ctx.assignment.revoked_by_account_id = ctx.owner.id
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.assignment.status = "active"
    ctx.assignment.ends_at = None
    ctx.assignment.revoked_at = None
    ctx.assignment.revoked_by_account_id = None

    ctx.assignment.starts_at = NOW + timedelta(seconds=1)
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.assignment.starts_at = NOW - timedelta(days=2)
    ctx.assignment.ends_at = NOW - timedelta(seconds=1)
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.assignment.ends_at = None

    ctx.position.is_active = False
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.position.is_active = True
    ctx.position.deleted_at = NOW
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.position.deleted_at = None

    ctx.access_profile.is_active = False
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )
    ctx.access_profile.is_active = True
    ctx.access_profile.deleted_at = NOW
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )


@pytest.mark.asyncio
async def test_scope_rules_and_resource_boundaries(access_context):
    ctx = access_context
    assert await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "employee.view",
        ctx.profile.id,
        NOW,
    )
    assert not await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "employee.view",
        ctx.target_profile.id,
        NOW,
    )
    assert not await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "venue.view",
        ctx.venue.id,
        NOW,
    )

    ctx.assignment.scope_type = "working_venues"
    await ctx.session.flush()
    assert await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "venue.view",
        ctx.venue.id,
        NOW,
    )
    assert not await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "venue.view",
        ctx.second_venue.id,
        NOW,
    )
    assert await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "employee.view",
        ctx.target_profile.id,
        NOW,
    )

    ctx.assignment.scope_type = "explicit_venues"
    await ctx.session.flush()
    assert await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "venue.view",
        ctx.second_venue.id,
        NOW,
    )
    assert not await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "employee.view",
        ctx.target_profile.id,
        NOW,
    )

    ctx.assignment.scope_type = "company"
    await ctx.session.flush()
    assert await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "employee.view",
        ctx.target_profile.id,
        NOW,
    )
    assert not await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "employee.view",
        ctx.other_profile.id,
        NOW,
    )
    assert not await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "venue.view",
        ctx.other_venue.id,
        NOW,
    )
    assert not await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "venue.view",
        ctx.closed_venue.id,
        NOW,
    )
    assert not await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "venue.view",
        ctx.deleted_venue.id,
        NOW,
    )


@pytest.mark.asyncio
async def test_assignments_do_not_mix_permission_and_scope(access_context):
    ctx = access_context
    permission_profile = AccessProfile(
        id=uuid4(),
        company_id=ctx.company.id,
        name="Audit",
        code=f"audit-{uuid4().hex[:8]}",
        maximum_scope="working_venues",
        is_system=False,
        is_active=True,
        version=1,
    )
    no_permission_profile = AccessProfile(
        id=uuid4(),
        company_id=ctx.company.id,
        name="No audit",
        code=f"no-audit-{uuid4().hex[:8]}",
        maximum_scope="working_venues",
        is_system=False,
        is_active=True,
        version=1,
    )
    ctx.session.add_all([permission_profile, no_permission_profile])
    await ctx.session.flush()
    ctx.session.add(
        AccessProfilePermission(
            access_profile_id=permission_profile.id,
            permission_code="audit.view",
        )
    )
    permission_assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=ctx.company.id,
        employee_profile_id=ctx.profile.id,
        position_id=ctx.position.id,
        access_profile_id=permission_profile.id,
        scope_type="working_venues",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    scope_assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=ctx.company.id,
        employee_profile_id=ctx.profile.id,
        position_id=ctx.position.id,
        access_profile_id=no_permission_profile.id,
        scope_type="working_venues",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    ctx.session.add_all([permission_assignment, scope_assignment])
    await ctx.session.flush()
    ctx.session.add_all(
        [
            AssignmentVenue(
                assignment_id=permission_assignment.id,
                venue_id=ctx.venue.id,
                company_id=ctx.company.id,
            ),
            AssignmentVenue(
                assignment_id=scope_assignment.id,
                venue_id=ctx.second_venue.id,
                company_id=ctx.company.id,
            ),
        ]
    )
    await ctx.session.flush()

    assert await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "audit.view",
        ctx.venue.id,
        NOW,
    )
    assert not await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "audit.view",
        ctx.second_venue.id,
        NOW,
    )

    satisfying_assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=ctx.company.id,
        employee_profile_id=ctx.profile.id,
        position_id=ctx.position.id,
        access_profile_id=permission_profile.id,
        scope_type="working_venues",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    ctx.session.add(satisfying_assignment)
    await ctx.session.flush()
    ctx.session.add(
        AssignmentVenue(
            assignment_id=satisfying_assignment.id,
            venue_id=ctx.second_venue.id,
            company_id=ctx.company.id,
        )
    )
    await ctx.session.flush()
    assert await ctx.service.can_for_venue(
        ctx.employee_account.id,
        ctx.company.id,
        "audit.view",
        ctx.second_venue.id,
        NOW,
    )


@pytest.mark.asyncio
async def test_maximum_scope_is_enforced(access_context):
    ctx = access_context
    assert not await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "limited.view",
        ctx.target_profile.id,
        NOW,
    )
    ctx.limited_assignment.scope_type = "self"
    await ctx.session.flush()
    assert await ctx.service.can_for_employee(
        ctx.employee_account.id,
        ctx.company.id,
        "limited.view",
        ctx.profile.id,
        NOW,
    )


@pytest.mark.asyncio
async def test_account_must_be_active_for_every_public_method(access_context):
    ctx = access_context
    ctx.assignment.scope_type = "company"
    await ctx.session.flush()

    assert await ctx.service.can_in_company(
        ctx.owner.id, ctx.company.id, "company.manage", NOW
    )
    assert await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )

    async def assert_all_denied(account_id):
        assert not await ctx.service.can_in_company(
            account_id, ctx.company.id, "employee.view", NOW
        )
        assert not await ctx.service.can_for_venue(
            account_id,
            ctx.company.id,
            "venue.view",
            ctx.venue.id,
            NOW,
        )
        assert not await ctx.service.can_for_employee(
            account_id,
            ctx.company.id,
            "employee.view",
            ctx.profile.id,
            NOW,
        )
        assert (
            await ctx.service.list_accessible_venue_ids(
                account_id, ctx.company.id, "venue.view", NOW
            )
            == set()
        )

    for account in (ctx.owner, ctx.employee_account):
        for status in ("suspended", "disabled"):
            account.status = status
            await ctx.session.flush()
            await assert_all_denied(account.id)
        account.status = "active"
        account.deleted_at = NOW
        await ctx.session.flush()
        await assert_all_denied(account.id)
        account.deleted_at = None
        await ctx.session.flush()


@pytest.mark.asyncio
async def test_can_in_company_requires_one_company_scope_assignment(access_context):
    ctx = access_context
    assert await ctx.service.can_in_company(
        ctx.owner.id, ctx.company.id, "company.manage", NOW
    )

    for scope_type in ("self", "working_venues", "explicit_venues"):
        ctx.assignment.scope_type = scope_type
        await ctx.session.flush()
        assert not await ctx.service.can_in_company(
            ctx.employee_account.id, ctx.company.id, "employee.view", NOW
        )

    ctx.assignment.scope_type = "company"
    await ctx.session.flush()
    assert await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )

    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "limited.view", NOW
    )

    scope_only_profile = AccessProfile(
        id=uuid4(),
        company_id=ctx.company.id,
        name="Scope only",
        code=f"scope-only-{uuid4().hex[:8]}",
        maximum_scope="company",
        is_system=False,
        is_active=True,
        version=1,
    )
    ctx.session.add(scope_only_profile)
    await ctx.session.flush()
    scope_only_assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=ctx.company.id,
        employee_profile_id=ctx.profile.id,
        position_id=ctx.position.id,
        access_profile_id=scope_only_profile.id,
        scope_type="company",
        is_primary=False,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    ctx.session.add(scope_only_assignment)
    ctx.assignment.scope_type = "self"
    await ctx.session.flush()
    assert not await ctx.service.can_in_company(
        ctx.employee_account.id, ctx.company.id, "employee.view", NOW
    )


@pytest.mark.asyncio
async def test_accessible_venue_lists(access_context):
    ctx = access_context
    owner_ids = await ctx.service.list_accessible_venue_ids(
        ctx.owner.id, ctx.company.id, "venue.view", NOW
    )
    assert owner_ids == {ctx.venue.id, ctx.second_venue.id}

    self_ids = await ctx.service.list_accessible_venue_ids(
        ctx.employee_account.id, ctx.company.id, "venue.view", NOW
    )
    assert self_ids == set()

    ctx.assignment.scope_type = "working_venues"
    ctx.session.add(
        AssignmentVenue(
            assignment_id=ctx.assignment.id,
            venue_id=ctx.second_venue.id,
            company_id=ctx.company.id,
        )
    )
    await ctx.session.flush()
    working_ids = await ctx.service.list_accessible_venue_ids(
        ctx.employee_account.id, ctx.company.id, "venue.view", NOW
    )
    assert working_ids == {ctx.venue.id, ctx.second_venue.id}

    ctx.assignment.scope_type = "company"
    await ctx.session.flush()
    company_ids = await ctx.service.list_accessible_venue_ids(
        ctx.employee_account.id, ctx.company.id, "venue.view", NOW
    )
    assert company_ids == {ctx.venue.id, ctx.second_venue.id}


@pytest.mark.asyncio
async def test_invalid_inputs_are_rejected_without_sql_patterns(access_context):
    ctx = access_context
    with pytest.raises(ValueError):
        await ctx.service.can_in_company(
            ctx.employee_account.id, ctx.company.id, "employee.%", NOW
        )
    with pytest.raises(ValueError):
        await ctx.service.can_in_company(
            str(ctx.employee_account.id),  # type: ignore[arg-type]
            ctx.company.id,
            "employee.view",
            NOW,
        )
