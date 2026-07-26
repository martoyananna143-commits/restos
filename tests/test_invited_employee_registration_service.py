"""PostgreSQL integration tests for atomic invited-employee registration."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.access_profile import AccessProfile
from app.infra.database.models.account import Account, AccountDevice, AccountIdentity, AccountSession
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import AssignmentScopeVenue, AssignmentVenue, EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.device_registration_challenge import DeviceRegistrationChallenge
from app.infra.database.models.invitation_v1 import Invitation, InvitationScopeVenue, InvitationVenue
from app.infra.database.models.phone_verification_challenge import PhoneVerificationChallenge
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue
from app.api.routers import account_invitation_auth as auth
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.account_session_service import AccountSessionService
from app.internal.services.invited_employee_registration_service import (
    BcryptPasswordHasher,
    InvalidInvitedEmployeeRegistration,
    InvitedEmployeeRegistrationService,
    InvitedEmployeeRegistrationUnavailable,
    RegisterInvitedEmployee,
)
from app.internal.services.device_registration_challenge_service import (
    InvalidDeviceRegistrationChallengeRequest,
    IssueDeviceRegistrationChallenge,
    DeviceRegistrationChallengeService,
    canonical_signed_message,
)
from app.internal.services.workforce_invitation_service import WorkforceInvitationService


NOW = datetime(2026, 7, 23, 16, 0, tzinfo=timezone.utc)
PHONE = "+79991234567"
CODE = "012345"
INVITATION_PEPPER = b"registration-invitation-pepper-32"
PHONE_PEPPER = b"registration-phone-pepper-32-byte"
SESSION_PEPPER = b"registration-session-pepper-32-b"


async def seed(session):
    owner = Account(id=uuid4(), display_name="Owner", status="active", security_version=1)
    session.add(owner)
    await session.flush()
    company = Company(id=uuid4(), owner_account_id=owner.id, name="Company", code=f"company-{uuid4().hex[:8]}", timezone="UTC", locale="ru-RU", status="active")
    session.add(company)
    await session.flush()
    access = AccessProfile(id=uuid4(), company_id=company.id, name="Access", code=f"access-{uuid4().hex[:8]}", maximum_scope="explicit_venues", is_system=False, is_active=True, version=1)
    position = Position(id=uuid4(), company_id=company.id, name="Waiter", code=f"waiter-{uuid4().hex[:8]}", is_active=True, sort_order=0)
    profile = EmployeeProfile(id=uuid4(), company_id=company.id, full_name="Invitee", phone=PHONE, employment_status="invited")
    venue1 = Venue(id=uuid4(), company_id=company.id, name="Work", code=f"work-{uuid4().hex[:8]}", status="active")
    venue2 = Venue(id=uuid4(), company_id=company.id, name="Scope", code=f"scope-{uuid4().hex[:8]}", status="active")
    session.add_all([access, position, profile, venue1, venue2])
    await session.flush()
    invitation = Invitation(
        id=uuid4(), company_id=company.id, employee_profile_id=profile.id,
        position_id=position.id, access_profile_id=access.id,
        scope_type="explicit_venues",
        code_digest=hmac.new(INVITATION_PEPPER, CODE.encode("ascii"), hashlib.sha256).digest(),
        status="pending", created_by_account_id=owner.id,
        expires_at=NOW + timedelta(hours=1), created_at=NOW - timedelta(minutes=5),
        updated_at=NOW - timedelta(minutes=5),
    )
    session.add(invitation)
    await session.flush()
    session.add_all([
        InvitationVenue(invitation_id=invitation.id, venue_id=venue1.id, company_id=company.id),
        InvitationScopeVenue(invitation_id=invitation.id, venue_id=venue2.id, company_id=company.id),
    ])
    phone_digest = hmac.new(PHONE_PEPPER, PHONE.encode("ascii"), hashlib.sha256).digest()
    challenge = PhoneVerificationChallenge(
        id=uuid4(), invitation_id=invitation.id, employee_profile_id=profile.id,
        purpose="invitation_registration", phone_digest=phone_digest,
        code_digest=b"c" * 32, status="verified", attempts_used=0, max_attempts=5,
        expires_at=NOW + timedelta(minutes=10), resend_available_at=NOW - timedelta(minutes=4),
        verified_at=NOW - timedelta(minutes=1), created_at=NOW - timedelta(minutes=5),
        updated_at=NOW - timedelta(minutes=1),
    )
    session.add(challenge)
    await session.flush()
    device_private_key = ec.generate_private_key(ec.SECP256R1())
    device_public_key = device_private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    device_nonce = b"n" * 32
    app_instance_id = uuid4()
    device_challenge = DeviceRegistrationChallenge(
        id=uuid4(), invitation_id=invitation.id,
        phone_verification_challenge_id=challenge.id,
        employee_profile_id=profile.id, app_instance_id=app_instance_id,
        platform="ios", public_key=device_public_key,
        public_key_fingerprint=hashlib.sha256(device_public_key).digest(),
        nonce_digest=b"x" * 32, status="pending",
        expires_at=NOW + timedelta(minutes=5), consumed_at=None,
        created_at=NOW, updated_at=NOW,
    )
    device_challenge.nonce_digest = DeviceRegistrationChallengeService._nonce_digest(
        device_challenge.id, invitation.id, challenge.id, app_instance_id,
        "ios", device_nonce,
    )
    session.add(device_challenge)
    await session.flush()
    return SimpleNamespace(
        owner=owner, company=company, access=access, position=position,
        profile=profile, venue1=venue1, venue2=venue2, invitation=invitation,
        challenge=challenge, device_challenge=device_challenge,
        device_private_key=device_private_key, device_nonce=device_nonce,
        app_instance_id=app_instance_id, device_public_key=device_public_key,
    )


@pytest_asyncio.fixture
async def context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    ctx = await seed(session)
    ctx.engine, ctx.connection, ctx.transaction, ctx.session = engine, connection, transaction, session
    try:
        yield ctx
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def make_service(session):
    return InvitedEmployeeRegistrationService(
        session,
        WorkforceInvitationService(session, AccessDecisionService(session), INVITATION_PEPPER),
        AccountSessionService(session, SESSION_PEPPER),
        DeviceRegistrationChallengeService(session, INVITATION_PEPPER, PHONE_PEPPER),
        INVITATION_PEPPER,
        PHONE_PEPPER,
    )


def request(ctx, **changes):
    signature = ctx.device_private_key.sign(
        canonical_signed_message(
            device_challenge_id=ctx.device_challenge.id,
            invitation_id=ctx.invitation.id,
            phone_challenge_id=ctx.challenge.id,
            app_instance_id=ctx.app_instance_id,
            platform="ios",
            nonce=ctx.device_nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )
    values = dict(
        invitation_code=CODE, phone_verification_challenge_id=ctx.challenge.id,
        phone=PHONE, display_name=" Anna Invitee ", password="correct horse battery",
        app_instance_id=ctx.app_instance_id, platform="ios",
        device_display_name="Anna iPhone",
        device_challenge_id=ctx.device_challenge.id,
        device_challenge_nonce=ctx.device_nonce,
        device_challenge_signature=signature, now=NOW,
    )
    values.update(changes)
    return RegisterInvitedEmployee(**values)


async def issue_device_challenge_over_http(context, monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(auth, "datetime", FixedDatetime)
    monkeypatch.setattr(
        auth.config, "ACCOUNT_AUTH_INVITATION_PEPPER", INVITATION_PEPPER.decode()
    )
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_PHONE_PEPPER", PHONE_PEPPER.decode())

    async def session_override():
        yield context.session

    app = FastAPI()
    auth.configure_account_auth_http_security(app)
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_account_auth_session] = session_override

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    app_instance_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as http:
        response = await http.post(
            "/api/v1/auth/invitations/device/challenge",
            json={
                "invitation_code": CODE,
                "phone_verification_challenge_id": str(context.challenge.id),
                "phone": PHONE,
                "app_instance_id": str(app_instance_id),
                "platform": "ios",
                "public_key": base64.b64encode(public_key).decode("ascii"),
            },
        )
    assert response.status_code == 200
    payload = response.json()
    nonce = base64.urlsafe_b64decode(payload["nonce"] + "==")
    return payload, private_key, app_instance_id, nonce


@pytest.mark.asyncio
async def test_http_device_challenge_invitation_id_is_registration_compatible(
    context, monkeypatch
):
    payload, private_key, app_instance_id, nonce = await issue_device_challenge_over_http(
        context, monkeypatch
    )
    invitation_id = UUID(payload["invitation_id"])
    device_challenge_id = UUID(payload["device_challenge_id"])
    signature = private_key.sign(
        canonical_signed_message(
            device_challenge_id=device_challenge_id,
            invitation_id=invitation_id,
            phone_challenge_id=context.challenge.id,
            app_instance_id=app_instance_id,
            platform="ios",
            nonce=nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )

    result = await make_service(context.session).register(
        request(
            context,
            app_instance_id=app_instance_id,
            device_challenge_id=device_challenge_id,
            device_challenge_nonce=nonce,
            device_challenge_signature=signature,
        )
    )

    assert invitation_id == context.invitation.id
    assert result.employee_profile_id == context.profile.id


@pytest.mark.asyncio
async def test_http_device_challenge_rejects_signature_with_wrong_invitation_id(
    context, monkeypatch
):
    payload, private_key, app_instance_id, nonce = await issue_device_challenge_over_http(
        context, monkeypatch
    )
    device_challenge_id = UUID(payload["device_challenge_id"])
    signature = private_key.sign(
        canonical_signed_message(
            device_challenge_id=device_challenge_id,
            invitation_id=uuid4(),
            phone_challenge_id=context.challenge.id,
            app_instance_id=app_instance_id,
            platform="ios",
            nonce=nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )

    with pytest.raises(InvitedEmployeeRegistrationUnavailable):
        await make_service(context.session).register(
            request(
                context,
                app_instance_id=app_instance_id,
                device_challenge_id=device_challenge_id,
                device_challenge_nonce=nonce,
                device_challenge_signature=signature,
            )
        )
    stored = await context.session.get(DeviceRegistrationChallenge, device_challenge_id)
    assert stored.status == "pending"
    assert stored.consumed_at is None


@pytest.mark.asyncio
async def test_success_is_complete_secret_safe_and_challenge_one_time(context):
    result = await make_service(context.session).register(request(context))
    account = await context.session.get(Account, result.account_id)
    identity = (await context.session.execute(select(AccountIdentity).where(AccountIdentity.account_id == result.account_id))).scalar_one()
    assignment = await context.session.get(EmployeeAssignment, result.employee_assignment_id)
    device = await context.session.get(AccountDevice, result.device_id)
    stored_session = await context.session.get(AccountSession, result.session_id)
    assert result.company_id == context.company.id and result.display_name == "Anna Invitee"
    assert BcryptPasswordHasher().verify("correct horse battery", account.password_hash)
    assert account.password_hash != "correct horse battery" and PHONE not in repr(identity.__dict__)
    assert identity.identity_type == "phone" and identity.provider == "e164"
    assert identity.status == "verified" and identity.is_primary is True
    assert identity.subject_digest == hmac.new(PHONE_PEPPER, PHONE.encode("ascii"), hashlib.sha256).digest()
    assert identity.subject_ciphertext is None
    assert context.invitation.status == "accepted" and context.profile.account_id == result.account_id
    assert assignment.position_id == context.position.id and assignment.access_profile_id == context.access.id
    assert set((await context.session.execute(select(AssignmentVenue.venue_id).where(AssignmentVenue.assignment_id == assignment.id))).scalars()) == {context.venue1.id}
    assert set((await context.session.execute(select(AssignmentScopeVenue.venue_id).where(AssignmentScopeVenue.assignment_id == assignment.id))).scalars()) == {context.venue2.id}
    assert device.quick_unlock_enabled is False and stored_session.status == "active"
    assert device.public_key == context.device_public_key
    assert context.device_challenge.status == "consumed"
    assert context.device_challenge.consumed_at == NOW
    assert context.challenge.consumed_at == NOW and context.challenge.consumed_by_account_id == result.account_id
    assert not hasattr(result, "password_hash") and not hasattr(result, "phone_digest")
    with pytest.raises(InvitedEmployeeRegistrationUnavailable):
        await make_service(context.session).register(request(context))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "expired", "locked", "cancelled"])
async def test_only_verified_challenge_is_available(context, status):
    context.challenge.status = status
    context.challenge.verified_at = None
    context.challenge.locked_at = NOW if status == "locked" else None
    context.challenge.cancelled_at = NOW if status == "cancelled" else None
    await context.session.flush()
    with pytest.raises(InvitedEmployeeRegistrationUnavailable):
        await make_service(context.session).register(request(context))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"phone": "+79990000000"}, {"invitation_code": "١٢٣٤٥٦"},
    {"password": "short"}, {"password": "я" * 40}, {"platform": "watchos"},
    {"device_challenge_signature": "not-bytes"}, {"now": datetime(2026, 7, 23, 16, 0)},
])
async def test_invalid_runtime_or_phone_is_controlled_and_outer_transaction_works(context, change):
    error = InvalidInvitedEmployeeRegistration if change.get("phone") is None else InvitedEmployeeRegistrationUnavailable
    with pytest.raises(error):
        await make_service(context.session).register(request(context, **change))
    assert (await context.session.execute(select(1))).scalar_one() == 1
    assert (await context.session.execute(select(func.count()).select_from(AccountIdentity))).scalar_one() == 0


@pytest.mark.asyncio
async def test_expired_consumed_or_wrong_context_challenge_is_unavailable(context):
    context.challenge.expires_at = NOW
    await context.session.flush()
    with pytest.raises(InvitedEmployeeRegistrationUnavailable):
        await make_service(context.session).register(request(context))
    context.challenge.expires_at = NOW + timedelta(minutes=1)
    other_profile = EmployeeProfile(
        id=uuid4(), company_id=context.company.id, full_name="Other invitee",
        phone="+79991234568", employment_status="invited",
    )
    context.session.add(other_profile)
    await context.session.flush()
    other_invitation = Invitation(
        id=uuid4(), company_id=context.company.id,
        employee_profile_id=other_profile.id, position_id=context.position.id,
        access_profile_id=context.access.id, scope_type="self",
        code_digest=hmac.new(
            INVITATION_PEPPER, b"654321", hashlib.sha256
        ).digest(),
        status="expired", created_by_account_id=context.owner.id,
        expires_at=NOW, created_at=NOW - timedelta(hours=1),
        updated_at=NOW,
    )
    context.session.add(other_invitation)
    await context.session.flush()
    context.challenge.invitation_id = other_invitation.id
    with pytest.raises(InvitedEmployeeRegistrationUnavailable):
        await make_service(context.session).register(request(context))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["accepted", "cancelled", "expired"])
async def test_non_pending_invitation_is_unavailable(context, status):
    context.invitation.status = status
    if status == "accepted":
        assignment_id = uuid4()
        assignment = EmployeeAssignment(
            id=assignment_id, company_id=context.company.id,
            employee_profile_id=context.profile.id,
            position_id=context.position.id,
            access_profile_id=context.access.id,
            scope_type="explicit_venues", is_primary=True,
            status="active", starts_at=NOW,
        )
        context.invitation.accepted_by_account_id = context.owner.id
        context.invitation.accepted_assignment_id = assignment_id
        context.invitation.accepted_at = NOW
        context.session.add(assignment)
        await context.session.flush()
    elif status == "cancelled":
        context.invitation.cancelled_at = NOW
        context.invitation.cancelled_by_account_id = context.owner.id
    await context.session.flush()
    with pytest.raises(InvitedEmployeeRegistrationUnavailable):
        await make_service(context.session).register(request(context))


@pytest.mark.asyncio
async def test_late_failure_rolls_back_outer_savepoint_and_session_remains_usable(context, monkeypatch):
    invitation_id = context.invitation.id
    employee_profile_id = context.profile.id
    challenge_id = context.challenge.id
    device_challenge_id = context.device_challenge.id
    service = make_service(context.session)
    original = service._account_sessions.register_device_and_issue_session
    async def fail_late(registration):
        await original(registration)
        raise RuntimeError("late failure")
    monkeypatch.setattr(service._account_sessions, "register_device_and_issue_session", fail_late)
    with pytest.raises(RuntimeError, match="late failure"):
        await service.register(request(context))
    context.session.expire_all()
    assert (await context.session.execute(select(func.count()).select_from(AccountIdentity))).scalar_one() == 0
    assert (await context.session.execute(select(func.count()).select_from(EmployeeAssignment))).scalar_one() == 0
    assert (await context.session.execute(select(func.count()).select_from(AccountDevice))).scalar_one() == 0
    assert (await context.session.execute(select(func.count()).select_from(AccountSession))).scalar_one() == 0
    assert (await context.session.get(Invitation, invitation_id)).status == "pending"
    profile = await context.session.get(EmployeeProfile, employee_profile_id)
    assert profile.account_id is None and profile.employment_status == "invited"
    challenge = await context.session.get(PhoneVerificationChallenge, challenge_id)
    assert challenge.consumed_at is None and challenge.consumed_by_account_id is None
    device_challenge = await context.session.get(
        DeviceRegistrationChallenge, device_challenge_id
    )
    assert device_challenge.status == "pending"
    assert device_challenge.consumed_at is None
    assert (await context.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_issue_device_challenge_stores_only_bound_nonce_digest(context):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    app_instance_id = uuid4()
    result = await DeviceRegistrationChallengeService(
        context.session, INVITATION_PEPPER, PHONE_PEPPER
    ).issue_challenge(
        IssueDeviceRegistrationChallenge(
            invitation_code=CODE,
            phone_verification_challenge_id=context.challenge.id,
            phone=PHONE,
            app_instance_id=app_instance_id,
            platform="ios",
            public_key=public_key,
            now=NOW,
        )
    )
    stored = await context.session.get(
        DeviceRegistrationChallenge, result.device_challenge_id
    )
    raw_nonce = __import__("base64").urlsafe_b64decode(result.nonce + "=")
    assert result.algorithm == "ES256"
    assert len(raw_nonce) == 32
    assert stored.public_key == public_key
    assert stored.public_key_fingerprint == hashlib.sha256(public_key).digest()
    assert stored.nonce_digest != raw_nonce
    assert raw_nonce not in stored.__dict__.values()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "public_key",
    [
        b"not-a-key",
        ec.generate_private_key(ec.SECP384R1()).public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    ],
)
async def test_issue_device_challenge_rejects_malformed_or_wrong_curve(
    context, public_key
):
    with pytest.raises(InvalidDeviceRegistrationChallengeRequest):
        await DeviceRegistrationChallengeService(
            context.session, INVITATION_PEPPER, PHONE_PEPPER
        ).issue_challenge(
            IssueDeviceRegistrationChallenge(
                invitation_code=CODE,
                phone_verification_challenge_id=context.challenge.id,
                phone=PHONE,
                app_instance_id=uuid4(),
                platform="ios",
                public_key=public_key,
                now=NOW,
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"device_challenge_signature": b"invalid-signature"},
        {"device_challenge_nonce": b"z" * 32},
        {"app_instance_id": uuid4()},
        {"platform": "web"},
    ],
)
async def test_device_proof_context_and_signature_are_bound(context, change):
    with pytest.raises(InvitedEmployeeRegistrationUnavailable):
        await make_service(context.session).register(request(context, **change))
    assert context.device_challenge.status == "pending"


@pytest.mark.asyncio
async def test_unknown_integrity_error_is_not_masked(context, monkeypatch):
    service = make_service(context.session)
    async def fail(_request):
        raise IntegrityError("insert", {}, RuntimeError("unknown constraint"))
    monkeypatch.setattr(service._workforce, "accept", fail)
    with pytest.raises(IntegrityError):
        await service.register(request(context))
    assert (await context.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_concurrent_registration_succeeds_once():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        ctx = await seed(setup)
        challenge_id = ctx.challenge.id
        invitation_id = ctx.invitation.id
        device_challenge_id = ctx.device_challenge.id
        device_private_key = ctx.device_private_key
        app_instance_id = ctx.app_instance_id
        device_nonce = ctx.device_nonce
        await setup.commit()
    async def attempt():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            local = SimpleNamespace(
                challenge=SimpleNamespace(id=challenge_id),
                invitation=SimpleNamespace(id=invitation_id),
                device_challenge=SimpleNamespace(id=device_challenge_id),
                device_private_key=device_private_key,
                app_instance_id=app_instance_id,
                device_nonce=device_nonce,
            )
            try:
                result = await make_service(session).register(request(local))
                await session.commit()
                return result
            except InvitedEmployeeRegistrationUnavailable as error:
                await session.rollback()
                return error
    results = await asyncio.gather(attempt(), attempt())
    assert sum(not isinstance(item, Exception) for item in results) == 1
    async with AsyncSession(engine) as verify:
        assert (await verify.execute(select(func.count()).select_from(AccountIdentity))).scalar_one() == 1
        assert (await verify.execute(select(func.count()).select_from(EmployeeAssignment))).scalar_one() == 1
        assert (await verify.execute(select(func.count()).select_from(AccountDevice))).scalar_one() == 1
        assert (await verify.execute(select(func.count()).select_from(AccountSession))).scalar_one() == 1
        challenge = await verify.get(PhoneVerificationChallenge, challenge_id)
        assert challenge.consumed_at == NOW
    await engine.dispose()
