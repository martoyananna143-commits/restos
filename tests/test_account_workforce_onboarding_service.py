"""PostgreSQL tests for Account-only workforce onboarding."""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.access_profile import AccessProfile, AccessProfilePermission
from app.infra.database.models.account import Account, AccountIdentity
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import Invitation, InvitationVenue
from app.infra.database.models.position import Position
from app.internal.services.account_workforce_onboarding_service import (
    AccountWorkforceOnboardingConflict,
    AccountWorkforceOnboardingForbidden,
    AccountWorkforceOnboardingInvalid,
    AccountWorkforceOnboardingService,
    CreateAccountWorkforceInvitation,
)
from app.internal.services.first_company_service import (
    CreateFirstCompany,
    FirstCompanyService,
)


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
PEPPER = b"p1-workforce-test-pepper-32-bytes-minimum"
PHONE_PEPPER = b"p1-workforce-phone-pepper-32-bytes-minimum"


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


async def owner_company(session: AsyncSession, *, venue: bool = True):
    account = Account(
        id=uuid4(),
        display_name="Synthetic Owner",
        password_hash="synthetic-hash",
        pin_hash=None,
        status="active",
        security_version=1,
        password_changed_at=NOW,
        last_login_at=None,
    )
    session.add(account)
    await session.flush()
    company = await FirstCompanyService(session).create(
        CreateFirstCompany(
            account_id=account.id,
            expected_security_version=1,
            company_name=f"Synthetic {uuid4().hex[:10]}",
            venue_name="Synthetic Venue" if venue else None,
            timezone="Europe/Moscow",
            locale="ru-RU",
            now=NOW,
        )
    )
    access = AccessProfile(
        id=uuid4(),
        company_id=company.company_id,
        name="Synthetic Invitation Access",
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
        company_id=company.company_id,
        name="Synthetic Employee Position",
        code=f"invite-position-{uuid4().hex[:12]}",
        description=None,
        default_access_profile_id=access.id,
        default_scope_type="working_venues" if venue else "self",
        is_active=True,
        sort_order=100,
    )
    session.add(position)
    await session.flush()
    return account, replace(
        company,
        position_id=position.id,
        access_profile_id=access.id,
    )


def command(owner, company, request_id, **changes):
    values = dict(
        actor_account_id=owner.id,
        company_id=company.company_id,
        request_id=request_id,
        employee_name=" Synthetic Employee ",
        phone=f"+7{request_id.int % 10_000_000_000:010d}",
        position_id=company.position_id,
        venue_id=company.venue_id,
        now=NOW,
    )
    values.update(changes)
    return CreateAccountWorkforceInvitation(**values)


@pytest.mark.asyncio
async def test_create_invitation_binds_normalized_phone_without_assignment(db_session):
    owner, company = await owner_company(db_session)
    request_id = uuid4()
    result = await AccountWorkforceOnboardingService(
        db_session, PEPPER, PHONE_PEPPER
    ).create_invitation(
        command(owner, company, request_id, phone="8 (999) 123-45-67")
    )
    profile = await db_session.get(EmployeeProfile, result.employee_profile_id)
    invitation = await db_session.get(Invitation, result.invitation_id)
    digest = hmac.new(PEPPER, result.code.encode("ascii"), hashlib.sha256).digest()
    assert result.created is True
    assert profile.full_name == "Synthetic Employee"
    assert profile.phone == "+79991234567"
    assert profile.account_id is None and profile.employment_status == "invited"
    assert invitation.company_id == company.company_id
    assert invitation.code_digest == digest and invitation.status == "pending"
    assert invitation.scope_type == "working_venues"
    assert await db_session.scalar(
        select(func.count()).select_from(InvitationVenue).where(
            InvitationVenue.invitation_id == invitation.id,
            InvitationVenue.venue_id == company.venue_id,
        )
    ) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(EmployeeAssignment).where(
            EmployeeAssignment.employee_profile_id == profile.id
        )
    ) == 0
    assert set(
        (
            await db_session.execute(
                select(AccessProfilePermission.permission_code).where(
            AccessProfilePermission.access_profile_id == invitation.access_profile_id
                )
            )
        ).scalars()
    ) == {"venue.view"}


@pytest.mark.asyncio
async def test_same_request_is_idempotent_and_code_is_recoverable(db_session):
    owner, company = await owner_company(db_session, venue=False)
    request_id = uuid4()
    service = AccountWorkforceOnboardingService(db_session, PEPPER, PHONE_PEPPER)
    before_profiles = await db_session.scalar(
        select(func.count()).select_from(EmployeeProfile)
    )
    first = await service.create_invitation(command(owner, company, request_id))
    second = await service.create_invitation(command(owner, company, request_id))
    after_profiles = await db_session.scalar(
        select(func.count()).select_from(EmployeeProfile)
    )
    assert first.created is True and second.created is False
    assert first.invitation_id == second.invitation_id
    assert first.employee_profile_id == second.employee_profile_id
    assert first.code == second.code
    assert first.delivery_status == "delivery_pending" and first.should_send is True
    assert second.delivery_status == "delivery_pending" and second.should_send is False
    assert first.delivery_attempt_count == second.delivery_attempt_count == 1
    assert after_profiles == before_profiles + 1


@pytest.mark.asyncio
async def test_failed_delivery_allows_one_idempotent_manual_retry(db_session):
    owner, company = await owner_company(db_session)
    request_id = uuid4()
    service = AccountWorkforceOnboardingService(db_session, PEPPER, PHONE_PEPPER)
    before_profiles = await db_session.scalar(
        select(func.count()).select_from(EmployeeProfile)
    )
    before_invitations = await db_session.scalar(
        select(func.count()).select_from(Invitation)
    )
    first = await service.create_invitation(command(owner, company, request_id))
    assert await service.record_delivery_outcome(
        first.invitation_id, "failed", NOW
    ) == "failed"

    retry = await service.create_invitation(command(owner, company, request_id))
    concurrent_duplicate = await service.create_invitation(
        command(owner, company, request_id)
    )

    assert retry.created is False and retry.should_send is True
    assert retry.delivery_status == "delivery_pending"
    assert retry.delivery_attempt_count == 2
    assert concurrent_duplicate.should_send is False
    assert concurrent_duplicate.delivery_attempt_count == 2
    assert await db_session.scalar(
        select(func.count()).select_from(EmployeeProfile)
    ) == before_profiles + 1
    assert await db_session.scalar(
        select(func.count()).select_from(Invitation)
    ) == before_invitations + 1


@pytest.mark.asyncio
async def test_unknown_delivery_never_resends(db_session):
    owner, company = await owner_company(db_session)
    request_id = uuid4()
    service = AccountWorkforceOnboardingService(db_session, PEPPER, PHONE_PEPPER)
    first = await service.create_invitation(command(owner, company, request_id))
    assert await service.record_delivery_outcome(
        first.invitation_id, "unknown", NOW
    ) == "unknown"

    repeated = await service.create_invitation(command(owner, company, request_id))

    assert repeated.created is False
    assert repeated.delivery_status == "unknown"
    assert repeated.should_send is False
    assert repeated.delivery_attempt_count == 1


@pytest.mark.asyncio
async def test_cross_company_actor_is_rejected_without_partial_profile(db_session):
    owner, company = await owner_company(db_session)
    outsider, _ = await owner_company(db_session)
    before = await db_session.scalar(select(func.count()).select_from(EmployeeProfile))
    with pytest.raises(AccountWorkforceOnboardingForbidden):
        await AccountWorkforceOnboardingService(
            db_session, PEPPER, PHONE_PEPPER
        ).create_invitation(command(outsider, company, uuid4()))
    after = await db_session.scalar(select(func.count()).select_from(EmployeeProfile))
    assert after == before
    assert await db_session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_owner_position_cannot_be_selected_for_employee_invitation(db_session):
    owner, company = await owner_company(db_session)
    owner_position_id = await db_session.scalar(
        select(Position.id).where(
            Position.company_id == company.company_id,
            Position.code == "owner",
        )
    )
    with pytest.raises(AccountWorkforceOnboardingInvalid):
        await AccountWorkforceOnboardingService(
            db_session, PEPPER, PHONE_PEPPER
        ).create_invitation(
            command(owner, company, uuid4(), position_id=owner_position_id)
        )
    assert await db_session.scalar(
        select(func.count()).select_from(Invitation).where(
            Invitation.company_id == company.company_id
        )
    ) == 0


@pytest.mark.asyncio
async def test_valid_existing_employee_access_profile_with_historical_id_is_reused(
    db_session,
):
    owner, company = await owner_company(db_session)
    historical_access = AccessProfile(
        id=uuid4(),
        company_id=company.company_id,
        name="Сотрудник",
        code="employee",
        description="Базовый доступ сотрудника",
        maximum_scope="working_venues",
        is_system=True,
        is_active=True,
        version=1,
    )
    db_session.add(historical_access)
    await db_session.flush()
    db_session.add(
        AccessProfilePermission(
            access_profile_id=historical_access.id,
            permission_code="venue.view",
        )
    )
    await db_session.flush()
    historical_position = Position(
        id=uuid4(),
        company_id=company.company_id,
        name="Historical Employee",
        code=f"historical-{uuid4().hex[:12]}",
        description=None,
        default_access_profile_id=historical_access.id,
        default_scope_type="working_venues",
        is_active=True,
        sort_order=110,
    )
    db_session.add(historical_position)
    await db_session.flush()

    request_id = uuid4()
    service = AccountWorkforceOnboardingService(db_session, PEPPER, PHONE_PEPPER)
    selected = dict(position_id=historical_position.id)
    first = await service.create_invitation(command(owner, company, request_id, **selected))
    second = await service.create_invitation(command(owner, company, request_id, **selected))
    invitation = await db_session.get(Invitation, first.invitation_id)
    access_count = await db_session.scalar(
        select(func.count()).select_from(AccessProfile).where(
            AccessProfile.company_id == company.company_id
        )
    )
    position_count = await db_session.scalar(
        select(func.count()).select_from(Position).where(
            Position.company_id == company.company_id
        )
    )
    await service.record_delivery_outcome(first.invitation_id, "failed", NOW)
    retry = await service.create_invitation(command(owner, company, request_id, **selected))

    assert first.created is True and second.created is False
    assert first.invitation_id == second.invitation_id
    assert retry.should_send is True and retry.delivery_attempt_count == 2
    assert invitation.access_profile_id == historical_access.id
    assert await db_session.scalar(
        select(func.count()).select_from(AccessProfile).where(
            AccessProfile.company_id == company.company_id
        )
    ) == access_count
    assert await db_session.scalar(
        select(func.count()).select_from(Position).where(
            Position.company_id == company.company_id
        )
    ) == position_count
    assert await db_session.scalar(
        select(func.count()).select_from(EmployeeProfile).where(
            EmployeeProfile.company_id == company.company_id,
            EmployeeProfile.full_name == "Synthetic Employee",
        )
    ) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(Invitation).where(
            Invitation.company_id == company.company_id,
            Invitation.employee_profile_id == first.employee_profile_id,
        )
    ) == 1


@pytest.mark.asyncio
async def test_rollback_removes_profile_defaults_and_invitation(db_session):
    owner, company = await owner_company(db_session)
    savepoint = await db_session.begin_nested()
    result = await AccountWorkforceOnboardingService(
        db_session, PEPPER, PHONE_PEPPER
    ).create_invitation(command(owner, company, uuid4()))
    await savepoint.rollback()
    assert await db_session.get(EmployeeProfile, result.employee_profile_id) is None
    assert await db_session.get(Invitation, result.invitation_id) is None


@pytest.mark.asyncio
async def test_ten_worker_same_request_has_one_mutation_and_idempotent_results():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    request_id = uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner, company = await owner_company(setup)
        owner_id = owner.id
        company_id = company.company_id
        position_id = company.position_id
        venue_id = company.venue_id
        await setup.commit()

    async def worker():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            result = await AccountWorkforceOnboardingService(
                session, PEPPER, PHONE_PEPPER
            ).create_invitation(
                CreateAccountWorkforceInvitation(
                    actor_account_id=owner_id,
                    company_id=company_id,
                    request_id=request_id,
                    employee_name="Concurrent Employee",
                    phone=f"+7{request_id.int % 10_000_000_000:010d}",
                    position_id=position_id,
                    venue_id=venue_id,
                    now=NOW,
                )
            )
            await session.commit()
            assert await session.scalar(select(1)) == 1
            return result

    results = await asyncio.gather(*(worker() for _ in range(10)))
    assert sum(result.created for result in results) == 1
    assert sum(result.should_send for result in results) == 1
    assert {result.delivery_status for result in results} == {"delivery_pending"}
    assert {result.delivery_attempt_count for result in results} == {1}
    assert len({result.invitation_id for result in results}) == 1
    assert len({result.code for result in results}) == 1
    async with AsyncSession(engine) as check:
        assert await check.scalar(
            select(func.count()).select_from(EmployeeProfile).where(
                EmployeeProfile.company_id == company_id,
                EmployeeProfile.full_name == "Concurrent Employee",
            )
        ) == 1
        assert await check.scalar(
            select(func.count()).select_from(Invitation).where(
                Invitation.company_id == company_id,
                Invitation.employee_profile_id == results[0].employee_profile_id,
            )
        ) == 1
        assert await check.scalar(
            select(func.count()).select_from(EmployeeAssignment).where(
                EmployeeAssignment.employee_profile_id
                == results[0].employee_profile_id
            )
        ) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_phone_and_missing_legacy_phone_fail_closed(db_session):
    owner, company = await owner_company(db_session)
    request_id = uuid4()
    service = AccountWorkforceOnboardingService(db_session, PEPPER, PHONE_PEPPER)
    with pytest.raises(AccountWorkforceOnboardingInvalid):
        await service.create_invitation(
            command(owner, company, request_id, phone="not-a-phone")
        )

    valid = command(owner, company, request_id)
    created = await service.create_invitation(valid)
    profile = await db_session.get(EmployeeProfile, created.employee_profile_id)
    profile.phone = None
    await db_session.flush()
    with pytest.raises(AccountWorkforceOnboardingConflict):
        await service.create_invitation(valid)
    assert await db_session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_existing_account_phone_is_not_enumerated_or_globally_blocked(db_session):
    owner, company = await owner_company(db_session)
    service = AccountWorkforceOnboardingService(db_session, PEPPER, PHONE_PEPPER)
    phone = "+79991234567"
    digest = hmac.new(PHONE_PEPPER, phone.encode("ascii"), hashlib.sha256).digest()
    account = Account(
        id=uuid4(),
        display_name="Synthetic Existing",
        password_hash="hash",
        pin_hash=None,
        status="active",
        security_version=1,
        password_changed_at=NOW,
        last_login_at=None,
    )
    db_session.add(account)
    await db_session.flush()
    db_session.add(
        AccountIdentity(
            id=uuid4(),
            account_id=account.id,
            identity_type="phone",
            provider="e164",
            subject_digest=digest,
            subject_ciphertext=None,
            passkey_credential_id=None,
            passkey_public_key=None,
            sign_count=None,
            verified_at=NOW,
            is_primary=True,
            status="verified",
            identity_metadata={},
            deleted_at=None,
        )
    )
    await db_session.flush()
    result = await service.create_invitation(
        command(owner, company, uuid4(), phone=phone)
    )
    profile = await db_session.get(EmployeeProfile, result.employee_profile_id)
    assert result.created is True
    assert profile.phone == phone and profile.account_id is None


@pytest.mark.asyncio
async def test_second_active_invitation_for_same_phone_is_rejected(db_session):
    owner, company = await owner_company(db_session)
    service = AccountWorkforceOnboardingService(db_session, PEPPER, PHONE_PEPPER)
    phone = "+79992345678"
    first = await service.create_invitation(
        command(owner, company, uuid4(), phone=phone)
    )
    with pytest.raises(AccountWorkforceOnboardingConflict):
        await service.create_invitation(command(owner, company, uuid4(), phone=phone))
    assert await db_session.get(Invitation, first.invitation_id) is not None
