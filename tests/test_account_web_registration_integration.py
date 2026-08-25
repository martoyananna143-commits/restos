"""PostgreSQL integration tests for invited browser registration."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import secrets
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.routers import account_invitation_auth
from app.infra.database.models.account import (
    Account,
    AccountDevice,
    AccountIdentity,
    AccountSession,
)
from app.infra.database.models.device_registration_challenge import (
    DeviceRegistrationChallenge,
)
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import Invitation
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.internal.services.account_access_token_service import (
    AccountAccessTokenService,
    VerifyAccountAccessToken,
)
from app.internal.services.device_registration_challenge_service import (
    canonical_signed_message,
)
from app.internal.services.account_legal_contract import (
    DOCUMENT_SET_VERSION,
    PRIVACY_VERSION,
    TERMS_VERSION,
)
from app.internal.services.invited_employee_registration_service import (
    InvitedEmployeeRegistrationService,
)
from tests.test_invited_employee_registration_service import (
    INVITATION_PEPPER,
    PHONE_PEPPER,
    SESSION_PEPPER,
    seed,
)


ORIGIN = "https://restos.test"
HEADERS = {"Origin": ORIGIN, "X-RestOS-Web-Session": "1"}
ACCESS_KEY = b"a" * 32


class FailingCommitSession(AsyncSession):
    async def commit(self):
        raise RuntimeError("commit failed")


@pytest_asyncio.fixture
async def web_registration_context(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as setup:
        for _attempt in range(20):
            invitation_code = f"{secrets.randbelow(1_000_000):06d}"
            code_digest = hmac.new(
                INVITATION_PEPPER,
                invitation_code.encode("ascii"),
                hashlib.sha256,
            ).digest()
            existing = (
                await setup.execute(
                    select(Invitation.id).where(
                        Invitation.code_digest == code_digest,
                        Invitation.status == "pending",
                        Invitation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                break
        else:
            raise RuntimeError("could not allocate a unique test invitation code")
        context = await seed(setup, code=invitation_code)
        context.invitation_code = invitation_code
        now = datetime.now(timezone.utc)
        phone = f"+79{uuid4().int % 10_000_000_000:010d}"
        context.phone = phone
        context.profile.phone = phone
        context.challenge.phone_digest = hmac.new(
            PHONE_PEPPER, phone.encode("ascii"), hashlib.sha256
        ).digest()
        context.invitation.created_at = now - timedelta(minutes=5)
        context.invitation.updated_at = now - timedelta(minutes=5)
        context.invitation.expires_at = now + timedelta(hours=1)
        context.challenge.created_at = now - timedelta(minutes=5)
        context.challenge.updated_at = now - timedelta(minutes=1)
        context.challenge.verified_at = now - timedelta(minutes=1)
        context.challenge.resend_available_at = now - timedelta(minutes=4)
        context.challenge.expires_at = now + timedelta(minutes=10)
        context.device_challenge.created_at = now
        context.device_challenge.updated_at = now
        context.device_challenge.expires_at = now + timedelta(minutes=5)
        await setup.commit()

    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_AUTH_INVITATION_PEPPER",
        INVITATION_PEPPER.decode(),
    )
    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_AUTH_PHONE_PEPPER",
        PHONE_PEPPER.decode(),
    )
    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_AUTH_SESSION_PEPPER",
        SESSION_PEPPER.decode(),
    )
    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_AUTH_ACCESS_TOKEN_KEY",
        ACCESS_KEY.decode(),
    )
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_ALLOWED_ORIGINS", [ORIGIN]
    )
    monkeypatch.setattr(
        account_invitation_auth.config,
        "ACCOUNT_WEB_REFRESH_COOKIE_NAME",
        "restos_refresh",
    )
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_REFRESH_COOKIE_SECURE", False
    )
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_REFRESH_COOKIE_SAMESITE", "lax"
    )
    monkeypatch.setattr(account_invitation_auth.config, "APP_ENV", "test")

    async def session_override():
        async with sessions() as session:
            yield session

    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(account_invitation_auth.router)
    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_override
    yield app, sessions, context
    await engine.dispose()


def _payload(context):
    signature = context.device_private_key.sign(
        canonical_signed_message(
            device_challenge_id=context.device_challenge.id,
            invitation_id=context.invitation.id,
            phone_challenge_id=context.challenge.id,
            app_instance_id=context.app_instance_id,
            platform="ios",
            nonce=context.device_nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )
    return {
        "invitation_code": context.invitation_code,
        "phone_verification_challenge_id": str(context.challenge.id),
        "phone": context.phone,
        "password": "correct horse battery",
        "app_instance_id": str(context.app_instance_id),
        "platform": "ios",
        "device_display_name": "Anna browser",
        "device_challenge_id": str(context.device_challenge.id),
        "device_challenge_nonce": base64.urlsafe_b64encode(
            context.device_nonce
        ).rstrip(b"=").decode(),
        "device_challenge_signature": base64.urlsafe_b64encode(signature)
        .rstrip(b"=")
        .decode(),
        "document_set_version": DOCUMENT_SET_VERSION,
        "terms_version": TERMS_VERSION,
        "privacy_version": PRIVACY_VERSION,
    }


async def _post(app, path, payload):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(path, headers=HEADERS, json=payload)


@pytest.mark.asyncio
async def test_real_web_registration_persists_and_sets_cookie_only(
    web_registration_context,
):
    app, sessions, context = web_registration_context
    response = await _post(
        app, "/api/v1/auth/invitations/register/web", _payload(context)
    )
    assert response.status_code == 200
    body = response.json()
    assert "refresh_token" not in body
    assert body["display_name"] == context.profile.full_name
    assert body["company_name"] == context.company.name
    assert body["position_name"] == context.position.name
    assert body["venue_names"]
    cookie = response.headers["set-cookie"]
    assert "restos_refresh=" in cookie
    assert "HttpOnly" in cookie and "Path=/api/v1/auth/web" in cookie
    assert "SameSite=lax" in cookie

    async with sessions() as verification:
        account_id = body["account_id"]
        account = await verification.get(Account, account_id)
        identity = (
            await verification.execute(
                select(AccountIdentity).where(
                    AccountIdentity.account_id == account.id
                )
            )
        ).scalar_one()
        assignment = await verification.get(
            EmployeeAssignment, body["employee_assignment_id"]
        )
        device = await verification.get(AccountDevice, body["device_id"])
        account_session = await verification.get(
            AccountSession, body["session_id"]
        )
        sms = await verification.get(
            PhoneVerificationChallenge, context.challenge.id
        )
        device_challenge = await verification.get(
            DeviceRegistrationChallenge, context.device_challenge.id
        )
        assert account and identity and assignment and device and account_session
        assert sms.consumed_at is not None
        assert device_challenge.status == "consumed"
        principal = await AccountAccessTokenService(
            verification, ACCESS_KEY
        ).verify(
            VerifyAccountAccessToken(
                access_token=body["access_token"],
                now=datetime.now(timezone.utc),
            )
        )
        assert str(principal.account_id) == body["account_id"]

    repeated = await _post(
        app, "/api/v1/auth/invitations/register/web", _payload(context)
    )
    assert repeated.status_code == 400
    assert "set-cookie" not in repeated.headers


@pytest.mark.asyncio
async def test_native_registration_contract_still_contains_refresh_token(
    web_registration_context, monkeypatch
):
    app, _sessions, context = web_registration_context
    response = await _post(
        app, "/api/v1/auth/invitations/register", _payload(context)
    )
    assert response.status_code == 200
    assert "refresh_token" in response.json()
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_web_registration_late_failure_rolls_back_without_cookie(
    web_registration_context, monkeypatch
):
    app, sessions, context = web_registration_context
    invitation_id = context.invitation.id
    employee_profile_id = context.profile.id
    sms_challenge_id = context.challenge.id
    device_challenge_id = context.device_challenge.id
    app_instance_id = context.app_instance_id
    identity_digest = hmac.new(
        PHONE_PEPPER, context.phone.encode("ascii"), hashlib.sha256
    ).digest()
    async with sessions() as baseline:
        account_ids_before = set(
            (await baseline.execute(select(Account.id))).scalars().all()
        )
    original = InvitedEmployeeRegistrationService.register

    async def fail_after_registration(self, request):
        await original(self, request)
        raise RuntimeError("late test failure")

    monkeypatch.setattr(
        InvitedEmployeeRegistrationService, "register", fail_after_registration
    )
    response = await _post(
        app, "/api/v1/auth/invitations/register/web", _payload(context)
    )
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_error"}}
    assert "set-cookie" not in response.headers

    async with sessions() as verification:
        account_ids_after = set(
            (await verification.execute(select(Account.id))).scalars().all()
        )
        invitation = await verification.get(Invitation, invitation_id)
        profile = await verification.get(EmployeeProfile, employee_profile_id)
        sms = await verification.get(
            PhoneVerificationChallenge, sms_challenge_id
        )
        device_challenge = await verification.get(
            DeviceRegistrationChallenge, device_challenge_id
        )
        identity = (
            await verification.execute(
                select(AccountIdentity.id).where(
                    AccountIdentity.subject_digest == identity_digest
                )
            )
        ).scalar_one_or_none()
        assignment = (
            await verification.execute(
                select(EmployeeAssignment.id).where(
                    EmployeeAssignment.employee_profile_id == employee_profile_id
                )
            )
        ).scalar_one_or_none()
        device = (
            await verification.execute(
                select(AccountDevice.id).where(
                    AccountDevice.app_instance_id == app_instance_id
                )
            )
        ).scalar_one_or_none()
        account_session = (
            await verification.execute(
                select(AccountSession.id)
                .join(AccountDevice, AccountDevice.id == AccountSession.device_id)
                .where(AccountDevice.app_instance_id == app_instance_id)
            )
        ).scalar_one_or_none()
        assert account_ids_after == account_ids_before
        assert invitation.status == "pending"
        assert profile.employment_status == "invited"
        assert profile.account_id is None
        assert sms.consumed_at is None
        assert device_challenge.status == "pending"
        assert identity is None
        assert assignment is None
        assert device is None
        assert account_session is None
        assert (
            await verification.execute(
                select(Invitation.id).where(Invitation.id == invitation_id)
            )
        ).scalar_one() == invitation_id


@pytest.mark.asyncio
async def test_web_registration_commit_failure_sets_no_cookie(
    web_registration_context,
):
    app, sessions, context = web_registration_context
    failing = async_sessionmaker(
        sessions.kw["bind"],
        class_=FailingCommitSession,
        expire_on_commit=False,
    )

    async def failing_session_override():
        async with failing() as session:
            yield session

    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = failing_session_override
    response = await _post(
        app, "/api/v1/auth/invitations/register/web", _payload(context)
    )
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_error"}}
    assert "set-cookie" not in response.headers
    async with sessions() as verification:
        invitation = await verification.get(Invitation, context.invitation.id)
        profile = await verification.get(EmployeeProfile, context.profile.id)
        assert invitation.status == "pending"
        assert profile.account_id is None


@pytest.mark.asyncio
async def test_concurrent_web_registration_has_one_winner(
    web_registration_context,
):
    app, sessions, context = web_registration_context
    payload = _payload(context)

    async def attempt():
        return await _post(
            app, "/api/v1/auth/invitations/register/web", payload
        )

    responses = await asyncio.gather(attempt(), attempt())
    assert sorted(response.status_code for response in responses) == [200, 400]
    winner = next(response for response in responses if response.status_code == 200)
    loser = next(response for response in responses if response.status_code == 400)
    assert "restos_refresh=" in winner.headers["set-cookie"]
    assert "set-cookie" not in loser.headers
    async with sessions() as verification:
        profile = await verification.get(EmployeeProfile, context.profile.id)
        assignments = (
            await verification.execute(
                select(EmployeeAssignment.id).where(
                    EmployeeAssignment.employee_profile_id == context.profile.id
                )
            )
        ).scalars().all()
        devices = (
            await verification.execute(
                select(AccountDevice.id).where(
                    AccountDevice.app_instance_id == context.app_instance_id
                )
            )
        ).scalars().all()
        assert profile.account_id is not None
        assert len(assignments) == 1
        assert len(devices) == 1
