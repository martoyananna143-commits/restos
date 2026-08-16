"""Production-workflow tests for owner Venue and employee access management."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.access_profile import AccessProfilePermission
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.venue import Venue
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.account_legal_contract import (
    AUTH_SMS_CONSENT_VERSION,
    DOCUMENT_SET_VERSION,
    PD_CONSENT_VERSION,
    PRIVACY_VERSION,
    REGISTRATION_OTP_MESSAGE_TYPE,
    TERMS_VERSION,
    AccountRegistrationAcceptance,
    RegistrationSmsConsent,
)
from app.internal.services.account_organization_access_service import (
    AccountOrganizationAccessService,
    CreateOrganizationVenue,
    OrganizationAccessConflict,
    OrganizationAccessNotFound,
    ReplaceEmployeeAccess,
    ReplaceEmployeePosition,
)
from app.internal.services.account_session_service import AccountSessionService
from app.internal.services.account_workforce_onboarding_service import (
    AccountWorkforceOnboardingService,
    CreateAccountWorkforceInvitation,
)
from app.internal.services.device_registration_challenge_service import (
    DeviceRegistrationChallengeService,
    IssueAccountDeviceRegistrationChallenge,
    canonical_account_registration_message,
)
from app.internal.services.first_company_service import (
    CreateFirstCompany,
    FirstCompanyService,
)
from app.internal.services.phone_verification_service import (
    PhoneVerificationService,
    RequestPhoneVerificationCode,
    VerifyPhoneVerificationCode,
)
from app.internal.services.organization_workflow_service import (
    CreatePosition,
    OrganizationWorkflowService,
)
from app.internal.services.standalone_account_auth_service import (
    RegisterStandaloneAccount,
    StandaloneAccountAuthService,
)
from app.internal.services.workforce_invitation_service import (
    AcceptWorkforceInvitation,
    WorkforceInvitationService,
)


NOW = datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc)
PHONE_PEPPER = b"organization-access-phone-pepper-32"
CODE_PEPPER = b"organization-access-code-pepper-32b"
SESSION_PEPPER = b"organization-access-session-pepper"
INVITATION_PEPPER = b"organization-access-invitation-pepper"


class ControlledSmsSender:
    def __init__(self):
        self.messages: list[dict[str, object]] = []

    async def send_verification_code(self, **message):
        self.messages.append(message)


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


async def register_account(session: AsyncSession, display_name: str):
    phone = f"+7999{uuid4().int % 10_000_000:07d}"
    sender = ControlledSmsSender()
    verification = PhoneVerificationService(
        session,
        sender,
        PHONE_PEPPER,
        CODE_PEPPER,
        "pilot.restos.space",
    )
    requested = await verification.request_code(
        RequestPhoneVerificationCode(
            purpose="account_registration",
            phone=phone,
            registration_sms_consent=RegistrationSmsConsent(
                personal_data_consent=True,
                personal_data_consent_version=PD_CONSENT_VERSION,
                authorization_sms_consent=True,
                authorization_sms_consent_version=AUTH_SMS_CONSENT_VERSION,
            ),
            auth_sms_message_type=REGISTRATION_OTP_MESSAGE_TYPE,
            now=NOW,
        )
    )
    code = sender.messages[-1]["code"]
    assert isinstance(code, str)
    await verification.verify_code(
        VerifyPhoneVerificationCode(
            challenge_id=requested.challenge_id,
            phone=phone,
            code=code,
            now=NOW + timedelta(seconds=1),
        )
    )
    device_service = DeviceRegistrationChallengeService(
        session, INVITATION_PEPPER, PHONE_PEPPER
    )
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    app_instance_id = uuid4()
    device = await device_service.issue_account_registration_challenge(
        IssueAccountDeviceRegistrationChallenge(
            phone_verification_challenge_id=requested.challenge_id,
            phone=phone,
            app_instance_id=app_instance_id,
            platform="web",
            public_key=public_key,
            now=NOW + timedelta(seconds=1),
        )
    )
    nonce = base64.urlsafe_b64decode(device.nonce + "=")
    signature = private_key.sign(
        canonical_account_registration_message(
            device_challenge_id=device.device_challenge_id,
            phone_challenge_id=requested.challenge_id,
            app_instance_id=app_instance_id,
            platform="web",
            nonce=nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )
    registered = await StandaloneAccountAuthService(
        session,
        AccountSessionService(session, SESSION_PEPPER),
        device_service,
        PHONE_PEPPER,
    ).register(
        RegisterStandaloneAccount(
            phone_verification_challenge_id=requested.challenge_id,
            phone=phone,
            display_name=display_name,
            password="correct horse battery",
            app_instance_id=app_instance_id,
            platform="web",
            device_display_name="Synthetic Browser",
            device_challenge_id=device.device_challenge_id,
            device_challenge_nonce=nonce,
            device_challenge_signature=signature,
            legal_acceptance=AccountRegistrationAcceptance(
                document_set_version=DOCUMENT_SET_VERSION,
                terms_version=TERMS_VERSION,
                privacy_version=PRIVACY_VERSION,
            ),
            now=NOW + timedelta(seconds=2),
        )
    )
    return SimpleNamespace(
        id=registered.account_id, display_name=display_name, phone=phone
    )


async def create_organization(session: AsyncSession, label: str):
    owner = await register_account(session, f"{label} Owner")
    company = await FirstCompanyService(session).create(
        CreateFirstCompany(
            account_id=owner.id,
            expected_security_version=1,
            company_name=f"{label} {uuid4().hex[:8]}",
            venue_name=f"{label} Venue One",
            timezone="Europe/Moscow",
            locale="ru-RU",
            now=NOW + timedelta(seconds=3),
        )
    )
    return owner, company


async def create_venue(session, owner, company, label="Second", request_id=None):
    return await AccountOrganizationAccessService(session).create_venue(
        CreateOrganizationVenue(
            owner.id,
            company.company_id,
            request_id or uuid4(),
            f"{label} Venue",
            None,
            NOW + timedelta(seconds=4),
        )
    )


async def join_employee(session, owner, company, venue_id, label="Employee"):
    account = await register_account(session, f"{label} {uuid4().hex[:6]}")
    request_id = uuid4()
    invited = await AccountWorkforceOnboardingService(
        session, INVITATION_PEPPER, PHONE_PEPPER
    ).create_invitation(
        CreateAccountWorkforceInvitation(
            owner.id,
            company.company_id,
            request_id,
            account.display_name,
            f"+7988{request_id.int % 10_000_000:07d}",
            venue_id,
            NOW + timedelta(seconds=5),
        )
    )
    accepted = await WorkforceInvitationService(
        session, AccessDecisionService(session), INVITATION_PEPPER
    ).accept(
        AcceptWorkforceInvitation(
            account_id=account.id,
            code=invited.code,
            now=NOW + timedelta(seconds=6),
        )
    )
    return account, accepted


@pytest.mark.asyncio
async def test_owner_venue_create_is_idempotent_and_company_scoped(session):
    owner, company = await create_organization(session, "Alpha")
    request_id = uuid4()
    first = await create_venue(session, owner, company, request_id=request_id)
    repeated = await create_venue(session, owner, company, request_id=request_id)
    listed = await AccountOrganizationAccessService(session).list_venues(
        owner.id, company.company_id, NOW + timedelta(seconds=5)
    )
    assert first["created"] is True and repeated["created"] is False
    assert first["venue_id"] == repeated["venue_id"]
    assert {row["venue_id"] for row in listed} == {
        company.venue_id,
        first["venue_id"],
    }
    assert await session.scalar(
        select(func.count()).select_from(Venue).where(
            Venue.company_id == company.company_id
        )
    ) == 2


@pytest.mark.asyncio
async def test_four_employee_access_profiles_are_atomic_and_policy_backed(session):
    owner, company = await create_organization(session, "Alpha")
    second = await create_venue(session, owner, company)
    employee, membership = await join_employee(
        session, owner, company, company.venue_id
    )
    service = AccountOrganizationAccessService(session)
    current = await service.employee_access(
        owner.id, company.company_id, membership.employee_profile_id, NOW + timedelta(seconds=7)
    )
    assert current["profile"] == "employee_venue"
    manager = await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            "venue_manager",
            (company.venue_id, second["venue_id"], company.venue_id),
            current["revision"],
            NOW + timedelta(seconds=8),
        )
    )
    assert manager["venue_ids"] == sorted(
        [company.venue_id, second["venue_id"]], key=str
    )
    decisions = AccessDecisionService(session)
    assert await decisions.can_for_venue(
        employee.id,
        company.company_id,
        "assessment.assignment.manage",
        second["venue_id"],
        NOW + timedelta(seconds=9),
    )
    assert not await decisions.can_in_company(
        employee.id,
        company.company_id,
        "assessment.assignment.manage",
        NOW + timedelta(seconds=9),
    )
    organization_manager = await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            "organization_manager",
            (),
            manager["revision"],
            NOW + timedelta(seconds=10),
        )
    )
    future = await create_venue(session, owner, company, "Future")
    visible = await decisions.list_accessible_venue_ids(
        employee.id,
        company.company_id,
        "assessment.assignment.read",
        NOW + timedelta(seconds=11),
    )
    assert organization_manager["venue_ids"] == []
    assert future["venue_id"] in visible
    unassigned = await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            "employee_unassigned",
            (),
            organization_manager["revision"],
            NOW + timedelta(seconds=12),
        )
    )
    rebound = await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            "employee_venue",
            (company.venue_id,),
            unassigned["revision"],
            NOW + timedelta(seconds=13),
        )
    )
    assert unassigned["profile"] == "employee_unassigned"
    assert rebound["profile"] == "employee_venue"


@pytest.mark.asyncio
async def test_owner_changes_employee_position_without_changing_access(session):
    owner, company = await create_organization(session, "Position")
    _, membership = await join_employee(
        session, owner, company, company.venue_id, "Position employee"
    )
    service = AccountOrganizationAccessService(session)
    current = await service.employee_access(
        owner.id,
        company.company_id,
        membership.employee_profile_id,
        NOW + timedelta(seconds=7),
    )
    replacement = await OrganizationWorkflowService(
        session, invitation_pepper=INVITATION_PEPPER
    ).create_position(
        CreatePosition(
            actor_account_id=owner.id,
            company_id=company.company_id,
            request_id=uuid4(),
            name="Старший сотрудник",
            description=None,
            access_preset="employee_venue",
            sort_order=200,
            now=NOW + timedelta(seconds=8),
        )
    )
    changed = await service.replace_employee_position(
        ReplaceEmployeePosition(
            actor_account_id=owner.id,
            company_id=company.company_id,
            employee_profile_id=membership.employee_profile_id,
            position_id=replacement["position_id"],
            expected_updated_at=current["revision"],
            now=NOW + timedelta(seconds=9),
        )
    )
    assert changed["position_id"] == replacement["position_id"]
    assert changed["position_name"] == "Старший сотрудник"
    assert changed["profile"] == current["profile"]
    assert changed["venue_ids"] == current["venue_ids"]


@pytest.mark.asyncio
async def test_owner_foreign_venue_and_stale_revision_fail_closed(session):
    owner, company = await create_organization(session, "Alpha")
    foreign_owner, foreign = await create_organization(session, "Foreign")
    _, membership = await join_employee(session, owner, company, company.venue_id)
    service = AccountOrganizationAccessService(session)
    current = await service.employee_access(
        owner.id, company.company_id, membership.employee_profile_id, NOW + timedelta(seconds=7)
    )
    with pytest.raises(OrganizationAccessNotFound):
        await service.replace_employee_access(
            ReplaceEmployeeAccess(
                foreign_owner.id,
                company.company_id,
                membership.employee_profile_id,
                "employee_unassigned",
                (),
                current["revision"],
                NOW + timedelta(seconds=8),
            )
        )
    with pytest.raises(OrganizationAccessNotFound):
        await service.replace_employee_access(
            ReplaceEmployeeAccess(
                owner.id,
                company.company_id,
                membership.employee_profile_id,
                "venue_manager",
                (foreign.venue_id,),
                current["revision"],
                NOW + timedelta(seconds=8),
            )
        )
    owner_access = await service.employee_access(
        owner.id, company.company_id, company.employee_profile_id, NOW + timedelta(seconds=7)
    )
    with pytest.raises(OrganizationAccessNotFound):
        await service.replace_employee_access(
            ReplaceEmployeeAccess(
                owner.id,
                company.company_id,
                company.employee_profile_id,
                "employee_unassigned",
                (),
                owner_access["revision"],
                NOW + timedelta(seconds=8),
            )
        )
    changed = await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            "employee_unassigned",
            (),
            current["revision"],
            NOW + timedelta(seconds=9),
        )
    )
    assert changed["profile"] == "employee_unassigned"
    with pytest.raises(OrganizationAccessConflict):
        await service.replace_employee_access(
            ReplaceEmployeeAccess(
                owner.id,
                company.company_id,
                membership.employee_profile_id,
                "organization_manager",
                (),
                current["revision"],
                NOW + timedelta(seconds=10),
            )
        )
    assert await session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_manager_permissions_are_exact_and_do_not_delegate_owner_mutations(session):
    owner, company = await create_organization(session, "Alpha")
    _, membership = await join_employee(session, owner, company, company.venue_id)
    service = AccountOrganizationAccessService(session)
    current = await service.employee_access(
        owner.id, company.company_id, membership.employee_profile_id, NOW + timedelta(seconds=7)
    )
    await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            "venue_manager",
            (company.venue_id,),
            current["revision"],
            NOW + timedelta(seconds=8),
        )
    )
    assignment = await session.get(EmployeeAssignment, membership.employee_assignment_id)
    permissions = set(
        (
            await session.execute(
                select(AccessProfilePermission.permission_code).where(
                    AccessProfilePermission.access_profile_id == assignment.access_profile_id
                )
            )
        ).scalars()
    )
    assert permissions == {
        "assessment.assignment.manage",
        "assessment.assignment.read",
        "assessment.template.read",
        "employee.activate",
        "employee.manage",
        "employee.view",
        "invitation.manage",
        "position.manage",
        "task.manage",
        "task.read",
        "task.review",
        "venue.view",
    }
    assert "employee.invite" not in permissions
    assert await session.scalar(
        select(func.count()).select_from(AssignmentScopeVenue).where(
            AssignmentScopeVenue.assignment_id == membership.employee_assignment_id
        )
    ) == 1
    assert await session.scalar(
        select(func.count()).select_from(AssignmentVenue).where(
            AssignmentVenue.assignment_id == membership.employee_assignment_id
        )
    ) == 0


@pytest.mark.asyncio
async def test_venue_manager_employee_access_is_limited_to_explicit_scope(session):
    owner, company = await create_organization(session, "Scoped")
    second = await create_venue(session, owner, company, "Foreign scope")
    manager, manager_membership = await join_employee(
        session, owner, company, company.venue_id, "Manager"
    )
    _, local_membership = await join_employee(
        session, owner, company, company.venue_id, "Local"
    )
    _, foreign_membership = await join_employee(
        session, owner, company, second["venue_id"], "Foreign"
    )
    service = AccountOrganizationAccessService(session)
    manager_access = await service.employee_access(
        owner.id,
        company.company_id,
        manager_membership.employee_profile_id,
        NOW + timedelta(seconds=7),
    )
    await service.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            manager_membership.employee_profile_id,
            "venue_manager",
            (company.venue_id,),
            manager_access["revision"],
            NOW + timedelta(seconds=8),
        )
    )
    visible = await service.list_employees(
        manager.id, company.company_id, NOW + timedelta(seconds=9)
    )
    visible_ids = {item["employee_profile_id"] for item in visible}
    assert local_membership.employee_profile_id in visible_ids
    assert foreign_membership.employee_profile_id not in visible_ids
    local = await service.employee_access(
        manager.id,
        company.company_id,
        local_membership.employee_profile_id,
        NOW + timedelta(seconds=9),
    )
    assert local["editable"] is True
    with pytest.raises(OrganizationAccessNotFound):
        await service.employee_access(
            manager.id,
            company.company_id,
            foreign_membership.employee_profile_id,
            NOW + timedelta(seconds=9),
        )
    with pytest.raises(OrganizationAccessNotFound):
        await service.replace_employee_access(
            ReplaceEmployeeAccess(
                manager.id,
                company.company_id,
                local_membership.employee_profile_id,
                "employee_venue",
                (second["venue_id"],),
                local["revision"],
                NOW + timedelta(seconds=10),
            )
        )


@pytest.mark.asyncio
async def test_ten_worker_venue_create_is_idempotent_on_dirty_database():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner, company = await create_organization(setup, "Concurrent Venue")
        request_id = uuid4()
        company_id = company.company_id
        owner_id = owner.id
        before = await setup.scalar(
            select(func.count()).select_from(Venue).where(Venue.company_id == company_id)
        )
        await setup.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def worker():
        nonlocal ready
        async with AsyncSession(engine, expire_on_commit=False) as worker_session:
            async with ready_lock:
                ready += 1
                if ready == 10:
                    start.set()
            await start.wait()
            result = await AccountOrganizationAccessService(worker_session).create_venue(
                CreateOrganizationVenue(
                    owner_id,
                    company_id,
                    request_id,
                    "Concurrent Venue",
                    "Europe/Moscow",
                    NOW + timedelta(minutes=1),
                )
            )
            await worker_session.commit()
            return result

    results = await asyncio.gather(*(worker() for _ in range(10)))
    async with AsyncSession(engine) as verify:
        after = await verify.scalar(
            select(func.count()).select_from(Venue).where(Venue.company_id == company_id)
        )
        request_rows = await verify.scalar(
            select(func.count()).select_from(Venue).where(
                Venue.company_id == company_id,
                Venue.meta["owner_request_id"].as_string() == str(request_id),
            )
        )
        assert await verify.scalar(select(1)) == 1
    await engine.dispose()
    assert sum(result["created"] is True for result in results) == 1
    assert sum(result["created"] is False for result in results) == 9
    assert len({result["venue_id"] for result in results}) == 1
    assert after == before + 1
    assert request_rows == 1


@pytest.mark.asyncio
async def test_ten_worker_access_replace_has_one_winner_and_nine_stale_conflicts():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner, company = await create_organization(setup, "Concurrent Access")
        second = await create_venue(setup, owner, company, "Concurrent Second")
        _, membership = await join_employee(
            setup, owner, company, company.venue_id, "Concurrent Employee"
        )
        current = await AccountOrganizationAccessService(setup).employee_access(
            owner.id,
            company.company_id,
            membership.employee_profile_id,
            NOW + timedelta(seconds=7),
        )
        owner_id = owner.id
        company_id = company.company_id
        employee_profile_id = membership.employee_profile_id
        assignment_id = membership.employee_assignment_id
        venue_ids = (company.venue_id, second["venue_id"])
        expected_revision = current["revision"]
        await setup.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def worker():
        nonlocal ready
        async with AsyncSession(engine, expire_on_commit=False) as worker_session:
            async with ready_lock:
                ready += 1
                if ready == 10:
                    start.set()
            await start.wait()
            try:
                result = await AccountOrganizationAccessService(
                    worker_session
                ).replace_employee_access(
                    ReplaceEmployeeAccess(
                        owner_id,
                        company_id,
                        employee_profile_id,
                        "venue_manager",
                        venue_ids,
                        expected_revision,
                        NOW + timedelta(minutes=2),
                    )
                )
                await worker_session.commit()
                return "success", result
            except OrganizationAccessConflict:
                await worker_session.rollback()
                assert await worker_session.scalar(select(1)) == 1
                return "conflict", None

    results = await asyncio.gather(*(worker() for _ in range(10)))
    async with AsyncSession(engine) as verify:
        scoped = set(
            (
                await verify.execute(
                    select(AssignmentScopeVenue.venue_id).where(
                        AssignmentScopeVenue.assignment_id == assignment_id
                    )
                )
            ).scalars()
        )
        working_rows = await verify.scalar(
            select(func.count()).select_from(AssignmentVenue).where(
                AssignmentVenue.assignment_id == assignment_id
            )
        )
        assert await verify.scalar(select(1)) == 1
    await engine.dispose()
    assert [status for status, _ in results].count("success") == 1
    assert [status for status, _ in results].count("conflict") == 9
    assert scoped == set(venue_ids)
    assert working_rows == 0
