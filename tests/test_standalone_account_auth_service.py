"""PostgreSQL tests for standalone Account registration and password auth."""

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from types import SimpleNamespace
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.account import (
    Account,
    AccountDevice,
    AccountIdentity,
    AccountSession,
)
from app.infra.database.models.account_legal_acceptance import AccountLegalAcceptance
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.internal.services.account_session_service import AccountSessionService
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
from app.internal.services.device_registration_challenge_service import (
    DeviceRegistrationChallengeService,
    IssueAccountDeviceRegistrationChallenge,
    canonical_account_registration_message,
)
from app.internal.services.phone_verification_service import (
    PhoneVerificationService,
    RequestPhoneVerificationCode,
    VerifyPhoneVerificationCode,
)
from app.internal.services.standalone_account_auth_service import (
    InvalidStandaloneAccountAuthRequest,
    LoginStandaloneAccount,
    RegisterStandaloneAccount,
    ResetStandaloneAccountPassword,
    StandaloneAccountAuthService,
    StandaloneAccountAuthUnavailable,
)


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
PHONE_PEPPER = b"standalone-phone-pepper-at-least-32-bytes"
SESSION_PEPPER = b"standalone-session-pepper-at-least-32-bytes"
INVITATION_PEPPER = b"standalone-invitation-pepper-at-least-32-bytes"
CODE_PEPPER = b"standalone-code-pepper-at-least-32-bytes"
PASSWORD = "correct horse battery"


def unique_phone() -> str:
    return f"+7999{uuid4().int % 10_000_000:07d}"


class FakeSmsSender:
    def __init__(self):
        self.messages = []

    async def send_verification_code(self, **message):
        self.messages.append(message)


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


def services(session: AsyncSession):
    device = DeviceRegistrationChallengeService(
        session, INVITATION_PEPPER, PHONE_PEPPER
    )
    auth = StandaloneAccountAuthService(
        session,
        AccountSessionService(session, SESSION_PEPPER),
        device,
        PHONE_PEPPER,
    )
    return auth, device


async def prepared_registration(
    session: AsyncSession, *, phone: str | None = None, now: datetime = NOW
):
    phone = phone or unique_phone()
    digest = hmac.new(PHONE_PEPPER, phone.encode("ascii"), hashlib.sha256).digest()
    challenge = PhoneVerificationChallenge(
        id=uuid4(),
        account_id=None,
        invitation_id=None,
        employee_profile_id=None,
        purpose="account_registration",
        phone_digest=digest,
        code_digest=b"c" * 32,
        status="verified",
        attempts_used=0,
        max_attempts=5,
        expires_at=now + timedelta(minutes=5),
        resend_available_at=now,
        verified_at=now,
        locked_at=None,
        cancelled_at=None,
        consumed_at=None,
        consumed_by_account_id=None,
        created_at=now - timedelta(minutes=1),
        updated_at=now,
    )
    session.add(challenge)
    await session.flush()
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    app_instance_id = uuid4()
    auth, device = services(session)
    issued = await device.issue_account_registration_challenge(
        IssueAccountDeviceRegistrationChallenge(
            phone_verification_challenge_id=challenge.id,
            phone=phone,
            app_instance_id=app_instance_id,
            platform="web",
            public_key=public_key,
            now=now,
        )
    )
    nonce = base64.urlsafe_b64decode(issued.nonce + "=")
    signature = private_key.sign(
        canonical_account_registration_message(
            device_challenge_id=issued.device_challenge_id,
            phone_challenge_id=challenge.id,
            app_instance_id=app_instance_id,
            platform="web",
            nonce=nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )
    return SimpleNamespace(
        auth=auth,
        phone=phone,
        phone_challenge=challenge,
        device_challenge_id=issued.device_challenge_id,
        app_instance_id=app_instance_id,
        private_key=private_key,
        public_key=public_key,
        nonce=nonce,
        signature=signature,
        now=now,
    )


def register_request(ctx, **changes):
    values = dict(
        phone_verification_challenge_id=ctx.phone_challenge.id,
        phone=ctx.phone,
        display_name=" Pilot Account ",
        password=PASSWORD,
        app_instance_id=ctx.app_instance_id,
        platform="web",
        device_display_name="Browser",
        device_challenge_id=ctx.device_challenge_id,
        device_challenge_nonce=ctx.nonce,
        device_challenge_signature=ctx.signature,
        legal_acceptance=AccountRegistrationAcceptance(
            document_set_version=DOCUMENT_SET_VERSION,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
        ),
        now=ctx.now,
    )
    values.update(changes)
    return RegisterStandaloneAccount(**values)


@pytest.mark.asyncio
async def test_account_registration_request_and_verify_success(db_session):
    sender = FakeSmsSender()
    verification = PhoneVerificationService(
        db_session,
        sender,
        PHONE_PEPPER,
        CODE_PEPPER,
        "pilot.restos.space",
        code_generator=lambda: "012345",
    )
    requested = await verification.request_code(
        RequestPhoneVerificationCode(
            purpose="account_registration",
            phone="8 (999) 123-45-67",
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
    verified = await verification.verify_code(
        VerifyPhoneVerificationCode(
            challenge_id=requested.challenge_id,
            phone="+79991234567",
            code="012345",
            now=NOW + timedelta(seconds=1),
        )
    )
    stored = await db_session.get(PhoneVerificationChallenge, requested.challenge_id)
    assert verified.purpose == "account_registration"
    assert stored.status == "verified" and stored.consumed_at is None
    assert sender.messages[0]["phone"] == "+79991234567"
    assert sender.messages[0]["purpose"] == "account_registration"
    assert not hasattr(stored, "phone") and not hasattr(stored, "code")


@pytest.mark.asyncio
async def test_registration_success_consumes_proofs_and_replay_is_rejected(db_session):
    ctx = await prepared_registration(db_session)
    result = await ctx.auth.register(register_request(ctx))
    account = await db_session.get(Account, result.account_id)
    identity = (
        await db_session.execute(
            select(AccountIdentity).where(AccountIdentity.account_id == account.id)
        )
    ).scalar_one()
    device = await db_session.get(AccountDevice, result.device_id)
    account_session = await db_session.get(AccountSession, result.session_id)
    legal = (
        await db_session.execute(
            select(AccountLegalAcceptance).where(
                AccountLegalAcceptance.account_id == account.id
            )
        )
    ).scalar_one()
    assert account.display_name == "Pilot Account"
    assert account.password_hash and account.password_hash != PASSWORD
    assert identity.status == "verified" and identity.is_primary is True
    assert identity.subject_digest == hmac.new(
        PHONE_PEPPER, ctx.phone.encode("ascii"), hashlib.sha256
    ).digest()
    assert not hasattr(identity, "phone")
    assert device.public_key == ctx.public_key and account_session.status == "active"
    assert legal.context == "account_registration"
    assert legal.document_set_version == DOCUMENT_SET_VERSION
    assert legal.accepted_at == ctx.now
    assert ctx.phone_challenge.consumed_by_account_id == account.id
    with pytest.raises(StandaloneAccountAuthUnavailable):
        await ctx.auth.register(register_request(ctx))
    assert (await db_session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_device_proof_rejects_cross_context_and_stale(db_session):
    ctx = await prepared_registration(db_session)
    wrong_signature = ctx.private_key.sign(
        canonical_account_registration_message(
            device_challenge_id=ctx.device_challenge_id,
            phone_challenge_id=uuid4(),
            app_instance_id=ctx.app_instance_id,
            platform="web",
            nonce=ctx.nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )
    with pytest.raises(StandaloneAccountAuthUnavailable):
        await ctx.auth.register(
            register_request(ctx, device_challenge_signature=wrong_signature)
        )
    with pytest.raises(StandaloneAccountAuthUnavailable):
        await ctx.auth.register(
            register_request(ctx, now=NOW + timedelta(minutes=6))
        )
    assert (await db_session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_login_normalizes_russian_phone_and_masks_bad_credentials(db_session):
    ctx = await prepared_registration(db_session, phone="+79991234567")
    registered = await ctx.auth.register(register_request(ctx))
    login_key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    logged_in = await ctx.auth.login(
        LoginStandaloneAccount(
            phone="8 (999) 123-45-67",
            password=PASSWORD,
            app_instance_id=uuid4(),
            platform="web",
            device_display_name=None,
            public_key=login_key,
            now=NOW + timedelta(seconds=1),
        )
    )
    assert logged_in.account_id == registered.account_id
    for phone, password in (
        (ctx.phone, "wrong password"),
        (unique_phone(), PASSWORD),
    ):
        with pytest.raises(StandaloneAccountAuthUnavailable) as caught:
            await ctx.auth.login(
                LoginStandaloneAccount(
                    phone=phone,
                    password=password,
                    app_instance_id=uuid4(),
                    platform="web",
                    device_display_name=None,
                    public_key=login_key,
                    now=NOW + timedelta(seconds=2),
                )
            )
        assert str(caught.value) == "authentication is unavailable"


@pytest.mark.asyncio
async def test_password_reset_increments_security_and_revokes_sessions(db_session):
    ctx = await prepared_registration(db_session)
    registered = await ctx.auth.register(register_request(ctx))
    reset_challenge = PhoneVerificationChallenge(
        id=uuid4(),
        account_id=registered.account_id,
        invitation_id=None,
        employee_profile_id=None,
        purpose="password_reset",
        phone_digest=hmac.new(
            PHONE_PEPPER, ctx.phone.encode("ascii"), hashlib.sha256
        ).digest(),
        code_digest=b"r" * 32,
        status="verified",
        attempts_used=0,
        max_attempts=5,
        expires_at=NOW + timedelta(minutes=5),
        resend_available_at=NOW,
        verified_at=NOW,
        locked_at=None,
        cancelled_at=None,
        consumed_at=None,
        consumed_by_account_id=None,
        created_at=NOW - timedelta(minutes=1),
        updated_at=NOW,
    )
    db_session.add(reset_challenge)
    await db_session.flush()
    result = await ctx.auth.reset_password(
        ResetStandaloneAccountPassword(
            phone_verification_challenge_id=reset_challenge.id,
            phone=ctx.phone,
            new_password="new correct horse battery",
            now=NOW + timedelta(seconds=5),
        )
    )
    account = await db_session.get(Account, registered.account_id)
    old_session = await db_session.get(AccountSession, registered.session_id)
    assert result.security_version == 2 and result.revoked_session_count == 1
    assert account.security_version == 2 and old_session.status == "revoked"
    assert reset_challenge.consumed_by_account_id == account.id
    with pytest.raises(StandaloneAccountAuthUnavailable):
        await ctx.auth.reset_password(
            ResetStandaloneAccountPassword(
                reset_challenge.id,
                ctx.phone,
                "another correct password",
                NOW + timedelta(seconds=6),
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["short", "я" * 37])
async def test_registration_password_byte_bounds(db_session, password):
    ctx = await prepared_registration(db_session)
    with pytest.raises(InvalidStandaloneAccountAuthRequest):
        await ctx.auth.register(register_request(ctx, password=password))


@pytest.mark.asyncio
async def test_duplicate_phone_is_rejected_without_extra_identity(db_session):
    phone = unique_phone()
    first = await prepared_registration(db_session, phone=phone)
    await first.auth.register(register_request(first))
    second = await prepared_registration(
        db_session, phone=phone, now=NOW + timedelta(seconds=1)
    )
    with pytest.raises(StandaloneAccountAuthUnavailable):
        await second.auth.register(register_request(second))
    count = (
        await db_session.execute(
            select(func.count()).select_from(AccountIdentity).where(
                AccountIdentity.subject_digest
                == hmac.new(PHONE_PEPPER, phone.encode("ascii"), hashlib.sha256).digest()
            )
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_phone_has_one_winner():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    phone = unique_phone()
    contexts = []
    for offset in range(2):
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            context = await prepared_registration(
                setup, phone=phone, now=NOW + timedelta(seconds=offset)
            )
            await setup.commit()
            contexts.append(context)

    async def worker(context):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            auth, _ = services(session)
            try:
                result = await auth.register(register_request(context))
                await session.commit()
                return result
            except StandaloneAccountAuthUnavailable as error:
                await session.rollback()
                assert (await session.execute(select(1))).scalar_one() == 1
                return error

    results = await asyncio.gather(*(worker(context) for context in contexts))
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, StandaloneAccountAuthUnavailable) for result in results) == 1
    digest = hmac.new(PHONE_PEPPER, phone.encode("ascii"), hashlib.sha256).digest()
    async with AsyncSession(engine) as verify:
        assert (
            await verify.execute(
                select(func.count()).select_from(AccountIdentity).where(
                    AccountIdentity.subject_digest == digest
                )
            )
        ).scalar_one() == 1
    await engine.dispose()
