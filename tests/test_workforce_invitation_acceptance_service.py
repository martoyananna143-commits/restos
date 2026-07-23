"""PostgreSQL integration tests for workforce invitation acceptance."""

from datetime import datetime, timedelta, timezone
import asyncio
import hashlib
import hmac
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.access_profile import AccessProfile
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import (
    Invitation,
    InvitationScopeVenue,
    InvitationVenue,
)
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.workforce_invitation_service import (
    AcceptWorkforceInvitation,
    AccountAlreadyMemberOfCompany,
    AccountUnavailableForInvitation,
    InvalidOrUnavailableInvitation,
    InvitationNoLongerApplicable,
    WorkforceInvitationService,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
PEPPER = b"acceptance-pepper" * 2


@pytest_asyncio.fixture
async def acceptance_context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    owner = Account(id=uuid4(), display_name="Owner", status="active")
    account = Account(id=uuid4(), display_name="Invitee", status="active")
    other_account = Account(id=uuid4(), display_name="Other", status="active")
    session.add_all([owner, account, other_account])
    await session.flush()
    company = Company(
        id=uuid4(), owner_account_id=owner.id, name="Company",
        code=f"accept-{uuid4().hex[:8]}", timezone="UTC", locale="ru-RU",
        status="active",
    )
    other_company = Company(
        id=uuid4(), owner_account_id=owner.id, name="Other company",
        code=f"other-{uuid4().hex[:8]}", timezone="UTC", locale="ru-RU",
        status="active",
    )
    session.add_all([company, other_company])
    await session.flush()
    access = AccessProfile(
        id=uuid4(), company_id=company.id, name="Access",
        code=f"access-{uuid4().hex[:8]}", maximum_scope="company",
        is_system=False, is_active=True, version=1,
    )
    position = Position(
        id=uuid4(), company_id=company.id, name="Position",
        code=f"position-{uuid4().hex[:8]}", is_active=True, sort_order=0,
    )
    profile = EmployeeProfile(
        id=uuid4(), company_id=company.id, full_name="Invitee",
        employment_status="invited",
    )
    venue1 = Venue(
        id=uuid4(), company_id=company.id, name="Venue 1",
        code=f"venue-{uuid4().hex[:8]}", status="active",
    )
    venue2 = Venue(
        id=uuid4(), company_id=company.id, name="Venue 2",
        code=f"venue-{uuid4().hex[:8]}", status="temporarily_closed",
    )
    session.add_all([access, position, profile, venue1, venue2])
    await session.flush()
    context = SimpleNamespace(
        engine=engine, connection=connection, transaction=transaction,
        session=session, owner=owner, account=account, other_account=other_account,
        company=company, other_company=other_company, access=access,
        position=position, profile=profile, venue1=venue1, venue2=venue2,
    )
    try:
        yield context
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def service(ctx, pepper=PEPPER):
    return WorkforceInvitationService(
        ctx.session, AccessDecisionService(ctx.session), pepper
    )


async def add_invitation(
    ctx, code="012345", status="pending", scope="explicit_venues",
    expires_at=NOW + timedelta(hours=1), deleted_at=None,
    working=True, scoped=True,
):
    invitation = Invitation(
        id=uuid4(), company_id=ctx.company.id,
        employee_profile_id=ctx.profile.id, position_id=ctx.position.id,
        access_profile_id=ctx.access.id, scope_type=scope,
        code_digest=hmac.new(PEPPER, code.encode("ascii"), hashlib.sha256).digest(),
        status=status, created_by_account_id=ctx.owner.id,
        expires_at=expires_at, created_at=NOW - timedelta(minutes=1),
        updated_at=NOW - timedelta(minutes=1), deleted_at=deleted_at,
    )
    if status == "accepted":
        assignment = EmployeeAssignment(
            id=uuid4(), company_id=ctx.company.id,
            employee_profile_id=ctx.profile.id, position_id=ctx.position.id,
            access_profile_id=ctx.access.id, scope_type=scope, is_primary=True,
            status="active", starts_at=NOW - timedelta(seconds=1),
        )
        ctx.session.add(assignment)
        await ctx.session.flush()
        invitation.accepted_by_account_id = ctx.account.id
        invitation.accepted_assignment_id = assignment.id
        invitation.accepted_at = NOW
    if status == "cancelled":
        invitation.cancelled_at = NOW
        invitation.cancelled_by_account_id = ctx.owner.id
    ctx.session.add(invitation)
    await ctx.session.flush()
    if working:
        ctx.session.add(InvitationVenue(
            invitation_id=invitation.id, venue_id=ctx.venue1.id,
            company_id=ctx.company.id,
        ))
    if scoped:
        ctx.session.add(InvitationScopeVenue(
            invitation_id=invitation.id, venue_id=ctx.venue2.id,
            company_id=ctx.company.id,
        ))
    await ctx.session.flush()
    return invitation


def accept_request(ctx, code="012345", account_id=None):
    return AcceptWorkforceInvitation(
        account_id=account_id or ctx.account.id, code=code, now=NOW
    )


@pytest.mark.asyncio
async def test_accepts_and_persists_all_invitation_data(acceptance_context, monkeypatch):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    compared = []
    original_compare = hmac.compare_digest
    monkeypatch.setattr(
        "app.internal.services.workforce_invitation_service.hmac.compare_digest",
        lambda left, right: compared.append((left, right)) or original_compare(left, right),
    )

    result = await service(ctx).accept(accept_request(ctx))
    await ctx.session.flush()
    assignment = await ctx.session.get(EmployeeAssignment, result.employee_assignment_id)
    working = set((await ctx.session.execute(select(AssignmentVenue.venue_id))).scalars())
    scoped = set((await ctx.session.execute(select(AssignmentScopeVenue.venue_id))).scalars())

    assert compared and result.invitation_id == invitation.id
    assert result.company_id == ctx.company.id
    assert result.employee_profile_id == ctx.profile.id
    assert result.position_id == ctx.position.id
    assert result.access_profile_id == ctx.access.id
    assert result.scope_type == "explicit_venues"
    assert result.working_venue_ids == working == {ctx.venue1.id}
    assert result.scope_venue_ids == scoped == {ctx.venue2.id}
    assert ctx.profile.account_id == ctx.account.id
    assert ctx.profile.employment_status == "active" and ctx.profile.hired_at == NOW
    assert assignment.status == "active" and assignment.is_primary is True
    assert assignment.starts_at == NOW and assignment.legacy_employee_id is None
    assert invitation.status == "accepted"
    assert invitation.accepted_by_account_id == ctx.account.id
    assert invitation.accepted_assignment_id == assignment.id
    assert invitation.accepted_at == NOW
    assert not hasattr(invitation, "code")


@pytest.mark.asyncio
async def test_existing_hired_at_is_preserved(acceptance_context):
    ctx = acceptance_context
    original_hired_at = NOW - timedelta(days=10)
    ctx.profile.hired_at = original_hired_at
    await add_invitation(ctx)
    await service(ctx).accept(accept_request(ctx))
    assert ctx.profile.hired_at == original_hired_at


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["١٢٣٤٥٦", "12345", "1234567", "12 345", "abcdef"])
async def test_rejects_non_ascii_or_non_six_digit_codes(acceptance_context, code):
    with pytest.raises(InvalidOrUnavailableInvitation):
        await service(acceptance_context).accept(accept_request(acceptance_context, code))


@pytest.mark.asyncio
async def test_wrong_and_reused_code_are_unavailable(acceptance_context):
    ctx = acceptance_context
    await add_invitation(ctx)
    with pytest.raises(InvalidOrUnavailableInvitation):
        await service(ctx).accept(accept_request(ctx, "999999"))
    await service(ctx).accept(accept_request(ctx))
    with pytest.raises(InvalidOrUnavailableInvitation):
        await service(ctx).accept(accept_request(ctx))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["accepted", "cancelled", "expired"])
async def test_non_pending_invitation_is_unavailable(acceptance_context, status):
    ctx = acceptance_context
    await add_invitation(ctx, status=status)
    with pytest.raises(InvalidOrUnavailableInvitation):
        await service(ctx).accept(accept_request(ctx))


@pytest.mark.asyncio
async def test_deleted_pending_is_unavailable(acceptance_context):
    ctx = acceptance_context
    await add_invitation(ctx, deleted_at=NOW)
    with pytest.raises(InvalidOrUnavailableInvitation):
        await service(ctx).accept(accept_request(ctx))


@pytest.mark.asyncio
async def test_factually_expired_pending_is_unavailable_without_changes(
    acceptance_context,
):
    ctx = acceptance_context
    invitation = await add_invitation(ctx, expires_at=NOW)
    with pytest.raises(InvalidOrUnavailableInvitation):
        await service(ctx).accept(accept_request(ctx))
    await assert_no_partial_acceptance(ctx, invitation)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,deleted", [
    ("suspended", False), ("disabled", False), ("active", True),
])
async def test_inactive_account_is_unavailable(acceptance_context, status, deleted):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    ctx.account.status = status
    ctx.account.deleted_at = NOW if deleted else None
    await ctx.session.flush()
    with pytest.raises(AccountUnavailableForInvitation):
        await service(ctx).accept(accept_request(ctx))
    await assert_no_partial_acceptance(ctx, invitation)


@pytest.mark.asyncio
async def test_unknown_account_is_unavailable(acceptance_context):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    with pytest.raises(AccountUnavailableForInvitation):
        await service(ctx).accept(accept_request(ctx, account_id=uuid4()))
    await assert_no_partial_acceptance(ctx, invitation)


@pytest.mark.asyncio
async def test_existing_profile_same_company_blocks_but_other_company_does_not(
    acceptance_context,
):
    ctx = acceptance_context
    await add_invitation(ctx)
    other_profile = EmployeeProfile(
        id=uuid4(), company_id=ctx.other_company.id, account_id=ctx.account.id,
        full_name="Other membership", employment_status="active",
    )
    ctx.session.add(other_profile)
    await ctx.session.flush()
    await service(ctx).accept(accept_request(ctx))


@pytest.mark.asyncio
async def test_existing_profile_in_same_company_is_rejected(acceptance_context):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    ctx.session.add(EmployeeProfile(
        id=uuid4(), company_id=ctx.company.id, account_id=ctx.account.id,
        full_name="Existing membership", employment_status="active",
    ))
    await ctx.session.flush()
    with pytest.raises(AccountAlreadyMemberOfCompany):
        await service(ctx).accept(accept_request(ctx))
    await assert_no_partial_acceptance(ctx, invitation)


async def assert_no_partial_acceptance(ctx, invitation):
    await ctx.session.refresh(ctx.profile)
    await ctx.session.refresh(invitation)
    assert ctx.profile.account_id is None
    assert invitation.status == "pending"
    assert invitation.accepted_assignment_id is None
    assignment_count = (
        await ctx.session.execute(
            select(func.count()).select_from(EmployeeAssignment).where(
                EmployeeAssignment.employee_profile_id == ctx.profile.id
            )
        )
    ).scalar_one()
    assert assignment_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_state", [
    "active", "suspended", "terminated", "linked", "deleted",
])
async def test_changed_employee_profile_is_rejected_without_partial_changes(
    acceptance_context, profile_state,
):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    if profile_state in {"active", "suspended", "terminated"}:
        ctx.profile.employment_status = profile_state
        ctx.profile.terminated_at = NOW if profile_state == "terminated" else None
    elif profile_state == "linked":
        ctx.profile.account_id = ctx.other_account.id
    else:
        ctx.profile.deleted_at = NOW
    await ctx.session.flush()
    with pytest.raises(InvitationNoLongerApplicable):
        await service(ctx).accept(accept_request(ctx))
    await ctx.session.refresh(invitation)
    assert invitation.status == "pending"
    assert not list((await ctx.session.execute(
        select(EmployeeAssignment).where(
            EmployeeAssignment.employee_profile_id == ctx.profile.id
        )
    )).scalars())


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    "company_suspended", "company_closed", "company_deleted",
    "position_inactive", "position_deleted", "access_inactive",
    "access_deleted", "scope_too_wide", "venue_closed", "venue_deleted",
])
async def test_changed_business_objects_are_rejected_atomically(
    acceptance_context, mutation,
):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    if mutation == "company_suspended":
        ctx.company.status = "suspended"
    elif mutation == "company_closed":
        ctx.company.status = "closed"
    elif mutation == "company_deleted":
        ctx.company.deleted_at = NOW
    elif mutation == "position_inactive":
        ctx.position.is_active = False
    elif mutation == "position_deleted":
        ctx.position.deleted_at = NOW
    elif mutation == "access_inactive":
        ctx.access.is_active = False
    elif mutation == "access_deleted":
        ctx.access.deleted_at = NOW
    elif mutation == "scope_too_wide":
        ctx.access.maximum_scope = "working_venues"
    elif mutation == "venue_closed":
        ctx.venue1.status = "closed"
    else:
        ctx.venue2.deleted_at = NOW
    await ctx.session.flush()
    with pytest.raises(InvitationNoLongerApplicable):
        await service(ctx).accept(accept_request(ctx))
    await assert_no_partial_acceptance(ctx, invitation)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,working,scoped", [
    ("working_venues", False, False),
    ("explicit_venues", True, False),
    ("self", True, True),
    ("company", True, True),
])
async def test_scope_list_rules_are_rechecked_at_acceptance(
    acceptance_context, scope, working, scoped,
):
    ctx = acceptance_context
    invitation = await add_invitation(
        ctx, scope=scope, working=working, scoped=scoped
    )
    with pytest.raises(InvitationNoLongerApplicable):
        await service(ctx).accept(accept_request(ctx))
    await assert_no_partial_acceptance(ctx, invitation)


@pytest.mark.asyncio
async def test_changed_business_data_rolls_back_without_partial_state(acceptance_context):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    ctx.position.is_active = False
    await ctx.session.flush()
    with pytest.raises(InvitationNoLongerApplicable):
        await service(ctx).accept(accept_request(ctx))
    await ctx.session.refresh(ctx.profile)
    await ctx.session.refresh(invitation)
    assert ctx.profile.account_id is None
    assert ctx.profile.employment_status == "invited"
    assert invitation.status == "pending"
    assert not list((await ctx.session.execute(select(EmployeeAssignment))).scalars())


@pytest.mark.asyncio
async def test_runtime_error_rolls_back_savepoint_and_keeps_outer_transaction_usable(
    acceptance_context, monkeypatch,
):
    ctx = acceptance_context
    invitation = await add_invitation(ctx)
    invitation_service = service(ctx)
    original = invitation_service._accept_locked

    async def fail_after_changes(request, digest):
        await original(request, digest)
        raise RuntimeError("artificial late failure")

    monkeypatch.setattr(invitation_service, "_accept_locked", fail_after_changes)
    with pytest.raises(RuntimeError, match="artificial late failure"):
        await invitation_service.accept(accept_request(ctx))
    await assert_no_partial_acceptance(ctx, invitation)
    assert not list((await ctx.session.execute(select(AssignmentVenue))).scalars())
    assert not list((await ctx.session.execute(select(AssignmentScopeVenue))).scalars())
    assert (await ctx.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_integrity_errors_are_classified_strictly(acceptance_context, monkeypatch):
    ctx = acceptance_context
    await add_invitation(ctx)
    invitation_service = service(ctx)

    class Diagnostic:
        constraint_name = "uq_employee_profiles_active_company_account"

    async def known_error(*_):
        raise IntegrityError("insert", {}, SimpleNamespace(diag=Diagnostic()))

    monkeypatch.setattr(invitation_service, "_accept_locked", known_error)
    with pytest.raises(AccountAlreadyMemberOfCompany):
        await invitation_service.accept(accept_request(ctx))

    class UnknownDiagnostic:
        constraint_name = "ck_unrelated_constraint"

    async def unknown_error(*_):
        raise IntegrityError("insert", {}, SimpleNamespace(diag=UnknownDiagnostic()))

    monkeypatch.setattr(invitation_service, "_accept_locked", unknown_error)
    with pytest.raises(IntegrityError):
        await invitation_service.accept(accept_request(ctx))


@pytest.mark.asyncio
async def test_two_sessions_accept_one_invitation_once():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    owner_id, first_id, second_id = uuid4(), uuid4(), uuid4()
    company_id, profile_id, access_id, position_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    venue_id, invitation_id = uuid4(), uuid4()
    code = "023456"
    digest = hmac.new(PEPPER, code.encode("ascii"), hashlib.sha256).digest()
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        setup.add_all([
            Account(id=owner_id, display_name="Owner", status="active"),
            Account(id=first_id, display_name="First", status="active"),
            Account(id=second_id, display_name="Second", status="active"),
        ])
        await setup.flush()
        setup.add(Company(
            id=company_id, owner_account_id=owner_id, name="Concurrent",
            code=f"concurrent-{uuid4().hex[:8]}", timezone="UTC", locale="ru-RU",
            status="active",
        ))
        await setup.flush()
        setup.add_all([
            AccessProfile(
                id=access_id, company_id=company_id, name="Access",
                code=f"concurrent-access-{uuid4().hex[:8]}", maximum_scope="company",
                is_system=False, is_active=True, version=1,
            ),
            Position(
                id=position_id, company_id=company_id, name="Position",
                code=f"concurrent-position-{uuid4().hex[:8]}",
                is_active=True, sort_order=0,
            ),
            EmployeeProfile(
                id=profile_id, company_id=company_id, full_name="Invitee",
                employment_status="invited",
            ),
            Venue(
                id=venue_id, company_id=company_id, name="Venue",
                code=f"concurrent-venue-{uuid4().hex[:8]}", status="active",
            ),
        ])
        await setup.flush()
        setup.add(Invitation(
            id=invitation_id, company_id=company_id, employee_profile_id=profile_id,
            position_id=position_id, access_profile_id=access_id,
            scope_type="working_venues", code_digest=digest, status="pending",
            created_by_account_id=owner_id, expires_at=NOW + timedelta(hours=1),
            created_at=NOW - timedelta(minutes=1), updated_at=NOW - timedelta(minutes=1),
        ))
        await setup.flush()
        setup.add(InvitationVenue(
            invitation_id=invitation_id, venue_id=venue_id, company_id=company_id
        ))
        await setup.commit()

    async def accept(account_id):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                invitation_service = WorkforceInvitationService(
                    session, AccessDecisionService(session), PEPPER
                )
                return await invitation_service.accept(
                    AcceptWorkforceInvitation(account_id=account_id, code=code, now=NOW)
                )

    results = await asyncio.gather(
        accept(first_id), accept(second_id), return_exceptions=True
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, InvalidOrUnavailableInvitation) for result in results) == 1
    async with AsyncSession(engine) as verify:
        invitation = await verify.get(Invitation, invitation_id)
        profile = await verify.get(EmployeeProfile, profile_id)
        assignments = list((await verify.execute(
            select(EmployeeAssignment).where(
                EmployeeAssignment.employee_profile_id == profile_id
            )
        )).scalars())
        joins = list((await verify.execute(
            select(AssignmentVenue).where(
                AssignmentVenue.assignment_id == assignments[0].id
            )
        )).scalars())
        assert invitation.status == "accepted"
        assert profile.account_id in {first_id, second_id}
        assert len(assignments) == 1 and len(joins) == 1
    await engine.dispose()
