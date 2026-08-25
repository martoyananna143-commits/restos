"""Production-workflow tests for phone-bound existing Account joins."""

import asyncio
from datetime import timedelta
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.account_legal_acceptance import AccountLegalAcceptance
from app.infra.database.models.access_profile import AccessProfile, AccessProfilePermission
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.account_workforce_onboarding_service import (
    AccountWorkforceOnboardingConflict,
    AccountWorkforceOnboardingService,
    CreateAccountWorkforceInvitation,
)
from app.internal.services.workforce_invitation_service import (
    AcceptAuthenticatedWorkforceInvitation,
    InvalidOrUnavailableInvitation,
    WorkforceInvitationService,
)
from tests.test_account_organization_access_service import (
    INVITATION_PEPPER,
    NOW,
    PHONE_PEPPER,
    create_organization,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    value = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield value
    finally:
        await value.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def onboarding(session: AsyncSession) -> AccountWorkforceOnboardingService:
    return AccountWorkforceOnboardingService(
        session, INVITATION_PEPPER, PHONE_PEPPER
    )


def joining(session: AsyncSession) -> WorkforceInvitationService:
    return WorkforceInvitationService(
        session, AccessDecisionService(session), INVITATION_PEPPER
    )


async def invitation_position(session: AsyncSession, company_id):
    access = AccessProfile(
        id=uuid4(),
        company_id=company_id,
        name="Synthetic Invite Access",
        code=f"invite-{uuid4().hex[:12]}",
        description=None,
        maximum_scope="working_venues",
        is_system=False,
        is_active=True,
        version=1,
    )
    session.add(access)
    await session.flush()
    session.add(
        AccessProfilePermission(
            access_profile_id=access.id,
            permission_code="venue.view",
        )
    )
    position = Position(
        id=uuid4(),
        company_id=company_id,
        name="Synthetic Invite Position",
        code=f"invite-position-{uuid4().hex[:12]}",
        description=None,
        default_access_profile_id=access.id,
        default_scope_type="working_venues",
        is_active=True,
        sort_order=100,
    )
    session.add(position)
    await session.flush()
    return position.id


async def context(session: AsyncSession):
    account, source = await create_organization(session, "Existing Source")
    target_owner, target = await create_organization(session, "Existing Target")
    position_id = await invitation_position(session, target.company_id)
    invitation = await onboarding(session).create_invitation(
        CreateAccountWorkforceInvitation(
            target_owner.id,
            target.company_id,
            uuid4(),
            account.display_name,
            account.phone,
            position_id,
            target.venue_id,
            NOW + timedelta(seconds=10),
        )
    )
    return account, source, target_owner, target, invitation


@pytest.mark.asyncio
async def test_existing_account_joins_second_company_idempotently_without_legal_delta(
    session,
):
    account, source, _, target, invitation = await context(session)
    legal_before = await session.scalar(
        select(func.count()).select_from(AccountLegalAcceptance).where(
            AccountLegalAcceptance.account_id == account.id
        )
    )
    first = await joining(session).accept_authenticated(
        AcceptAuthenticatedWorkforceInvitation(
            account.id, invitation.code, NOW + timedelta(seconds=20)
        ),
        PHONE_PEPPER,
    )
    repeated = await joining(session).accept_authenticated(
        AcceptAuthenticatedWorkforceInvitation(
            account.id, invitation.code, NOW + timedelta(seconds=21)
        ),
        PHONE_PEPPER,
    )
    profiles = (
        await session.execute(
            select(EmployeeProfile).where(
                EmployeeProfile.account_id == account.id,
                EmployeeProfile.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    assert {profile.company_id for profile in profiles} == {
        source.company_id,
        target.company_id,
    }
    assert first.employee_assignment_id == repeated.employee_assignment_id
    assert len(profiles) == 2
    assert await session.scalar(
        select(func.count()).select_from(AccountLegalAcceptance).where(
            AccountLegalAcceptance.account_id == account.id
        )
    ) == legal_before


@pytest.mark.asyncio
async def test_wrong_account_expired_and_unknown_codes_share_unavailable_contract(
    session,
):
    account, _, other, _, invitation = await context(session)
    cases = (
        AcceptAuthenticatedWorkforceInvitation(other.id, invitation.code, NOW),
        AcceptAuthenticatedWorkforceInvitation(
            account.id, invitation.code, NOW + timedelta(days=2)
        ),
        AcceptAuthenticatedWorkforceInvitation(account.id, "000000", NOW),
    )
    for request in cases:
        with pytest.raises(InvalidOrUnavailableInvitation):
            await joining(session).accept_authenticated(request, PHONE_PEPPER)
        assert await session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_ten_worker_accept_has_one_membership_and_stable_result():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        account, _, _, target, invitation = await context(setup)
        account_id, target_id, code = account.id, target.company_id, invitation.code
        await setup.commit()

    async def worker():
        async with AsyncSession(engine, expire_on_commit=False) as current:
            result = await joining(current).accept_authenticated(
                AcceptAuthenticatedWorkforceInvitation(
                    account_id, code, NOW + timedelta(seconds=20)
                ),
                PHONE_PEPPER,
            )
            await current.commit()
            assert await current.scalar(select(1)) == 1
            return result

    results = await asyncio.gather(*(worker() for _ in range(10)))
    assert len({item.employee_profile_id for item in results}) == 1
    assert len({item.employee_assignment_id for item in results}) == 1
    async with AsyncSession(engine) as check:
        assert await check.scalar(
            select(func.count()).select_from(EmployeeProfile).where(
                EmployeeProfile.account_id == account_id,
                EmployeeProfile.company_id == target_id,
                EmployeeProfile.deleted_at.is_(None),
            )
        ) == 1
        assert await check.scalar(
            select(func.count()).select_from(EmployeeAssignment).where(
                EmployeeAssignment.id == results[0].employee_assignment_id
            )
        ) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_ten_worker_create_same_company_phone_has_one_winner():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner, company = await create_organization(setup, "Concurrent Target")
        invited, _ = await create_organization(setup, "Concurrent Existing")
        invitation_position_id = await invitation_position(setup, company.company_id)
        owner_id, company_id, position_id, venue_id = (
            owner.id,
            company.company_id,
            invitation_position_id,
            company.venue_id,
        )
        phone = invited.phone
        await setup.commit()

    async def worker():
        async with AsyncSession(engine, expire_on_commit=False) as current:
            try:
                result = await onboarding(current).create_invitation(
                    CreateAccountWorkforceInvitation(
                        owner_id,
                        company_id,
                        uuid4(),
                        "Concurrent Same Phone",
                        phone,
                        position_id,
                        venue_id,
                        NOW,
                    )
                )
                await current.commit()
                return result.created
            except AccountWorkforceOnboardingConflict:
                await current.rollback()
                assert await current.scalar(select(1)) == 1
                return False

    results = await asyncio.gather(*(worker() for _ in range(10)))
    assert results.count(True) == 1 and results.count(False) == 9
    async with AsyncSession(engine) as check:
        assert await check.scalar(
            select(func.count()).select_from(EmployeeProfile).where(
                EmployeeProfile.company_id == company_id,
                EmployeeProfile.phone == phone,
                EmployeeProfile.deleted_at.is_(None),
            )
        ) == 1
    await engine.dispose()
