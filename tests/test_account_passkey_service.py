"""Focused Stage 22A passkey security and transaction tests."""

from datetime import datetime, timedelta, timezone
import asyncio
import base64
import hashlib
import hmac
import os
import secrets
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from webauthn.helpers.structs import CredentialDeviceType

from app.infra.database.models.account import (
    Account,
    AccountDevice,
    AccountIdentity,
    AccountSession,
)
from app.infra.database.models.account_webauthn_challenge import (
    AccountWebAuthnChallenge,
)
import app.internal.services.account_passkey_service as passkey_module
from app.internal.services.account_passkey_service import (
    AccountPasskeyService,
    AccountPasskeyRateLimited,
    AuthenticationVerified,
    PasskeyRejected,
    _signed_bigint,
    authentication_bucket_lock_key,
    credential_device_type_is_backup_eligible,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    IssuedDeviceSession,
)


NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest_asyncio.fixture
async def passkey_context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    raw_challenge = secrets.token_bytes(32)
    account = Account(
        id=uuid4(),
        display_name="Passkey account",
        status="active",
        security_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(account)
    await session.flush()
    device_private_key = ec.generate_private_key(ec.SECP256R1())
    device_public_key = device_private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    device = AccountDevice(
        id=uuid4(),
        account_id=account.id,
        app_instance_id=uuid4(),
        platform="web",
        display_name="Existing browser",
        public_key=device_public_key,
        public_key_fingerprint=hashlib.sha256(device_public_key).digest(),
        quick_unlock_enabled=False,
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(device)
    await session.flush()
    account_session = AccountSession(
        id=uuid4(),
        account_id=account.id,
        device_id=device.id,
        token_selector=uuid4(),
        refresh_secret_digest=hashlib.sha256(uuid4().bytes).digest(),
        refresh_family=uuid4(),
        previous_rotated_session_id=None,
        security_version=1,
        status="active",
        issued_at=NOW,
        idle_expires_at=NOW + timedelta(hours=1),
        absolute_expires_at=NOW + timedelta(hours=2),
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(account_session)
    await session.flush()
    try:
        yield SimpleNamespace(
            engine=engine,
            connection=connection,
            transaction=transaction,
            session=session,
            account=account,
            device=device,
            account_session=account_session,
            raw_challenge=raw_challenge,
        )
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def service(context):
    return AccountPasskeyService(
        context.session,
        rp_id="restos.test",
        rp_name="RestOS",
        allowed_origins=("https://restos.test",),
        session_pepper=b"p" * 32,
        challenge_ttl=timedelta(minutes=5),
        max_verify_attempts=3,
    )


def service_for_session(session):
    return AccountPasskeyService(
        session,
        rp_id="restos.test",
        rp_name="RestOS",
        allowed_origins=("https://restos.test",),
        session_pepper=b"p" * 32,
        challenge_ttl=timedelta(minutes=5),
        max_verify_attempts=3,
    )


def authentication_context():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return uuid4(), public_key, b"rate-subject-" + uuid4().bytes


def authentication_bucket(app_instance_id, public_key, rate_subject):
    context_digest = AccountPasskeyService._device_context_digest(
        app_instance_id, "web", public_key
    )
    return hmac.new(
        b"p" * 32,
        b"webauthn-auth-begin-v1" + rate_subject + context_digest,
        hashlib.sha256,
    ).digest()


def _patch_client_data(monkeypatch, *, registration, raw_challenge):
    response = SimpleNamespace(client_data_json=b"client-data", transports=[])
    parsed = SimpleNamespace(response=response, raw_id=b"credential-id")
    monkeypatch.setattr(
        passkey_module,
        (
            "parse_registration_credential_json"
            if registration
            else "parse_authentication_credential_json"
        ),
        lambda _credential: parsed,
    )
    monkeypatch.setattr(
        passkey_module,
        "parse_client_data_json",
        lambda _client_data: SimpleNamespace(challenge=raw_challenge),
    )
    return parsed


async def _registration_challenge(context):
    challenge = AccountWebAuthnChallenge(
        id=uuid4(),
        ceremony_type="registration",
        challenge_digest=hashlib.sha256(context.raw_challenge).digest(),
        account_id=context.account.id,
        session_id=context.account_session.id,
        attempts=0,
        status="pending",
        expires_at=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )
    context.session.add(challenge)
    await context.session.flush()
    return challenge


@pytest.mark.parametrize(
    ("device_type", "expected"),
    [
        (CredentialDeviceType.SINGLE_DEVICE, False),
        (CredentialDeviceType.MULTI_DEVICE, True),
    ],
)
def test_credential_device_type_maps_to_immutable_backup_eligibility(
    device_type, expected
):
    assert credential_device_type_is_backup_eligible(device_type) is expected


@pytest.mark.parametrize("client_supplied_backup_flag", [False, True])
def test_backup_eligibility_mapping_ignores_client_supplied_flags(
    client_supplied_backup_flag,
):
    del client_supplied_backup_flag
    assert (
        credential_device_type_is_backup_eligible(
            CredentialDeviceType.SINGLE_DEVICE
        )
        is False
    )
    assert (
        credential_device_type_is_backup_eligible(
            CredentialDeviceType.MULTI_DEVICE
        )
        is True
    )


def test_unknown_credential_device_type_is_rejected():
    with pytest.raises(ValueError, match="credential device type is unavailable"):
        credential_device_type_is_backup_eligible(object())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("device_type", "backed_up", "expected_eligible", "accepted"),
    [
        (CredentialDeviceType.SINGLE_DEVICE, False, False, True),
        (CredentialDeviceType.MULTI_DEVICE, True, True, True),
        (CredentialDeviceType.SINGLE_DEVICE, True, False, False),
    ],
)
async def test_registration_uses_verified_backup_flags(
    passkey_context,
    monkeypatch,
    device_type,
    backed_up,
    expected_eligible,
    accepted,
):
    challenge = await _registration_challenge(passkey_context)
    _patch_client_data(
        monkeypatch,
        registration=True,
        raw_challenge=passkey_context.raw_challenge,
    )
    credential_id = b"registration-" + uuid4().bytes
    monkeypatch.setattr(
        passkey_module,
        "verify_registration_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=credential_id,
            credential_public_key=b"verified-cose-key",
            sign_count=0,
            credential_device_type=device_type,
            credential_backed_up=backed_up,
        ),
    )
    result = await service(passkey_context).verify_registration(
        challenge_id=challenge.id,
        account_id=passkey_context.account.id,
        session_id=passkey_context.account_session.id,
        credential={},
        display_name="Passkey",
        now=NOW,
    )
    identities = list(
        (
            await passkey_context.session.execute(
                select(AccountIdentity).where(
                    AccountIdentity.account_id == passkey_context.account.id,
                    AccountIdentity.identity_type == "passkey",
                    AccountIdentity.passkey_credential_id == credential_id,
                )
            )
        ).scalars()
    )
    if accepted:
        assert len(identities) == 1
        assert identities[0].passkey_backup_eligible is expected_eligible
        assert identities[0].passkey_backup_state is backed_up
        assert challenge.status == "consumed"
    else:
        assert isinstance(result, PasskeyRejected)
        assert identities == []
        assert challenge.status == "pending"
        assert challenge.attempts == 1


class _RecordingSessionService:
    def __init__(self, account_id):
        self.account_id = account_id
        self.calls = 0

    async def register_device_and_issue_session(self, request):
        self.calls += 1
        return IssuedDeviceSession(
            account_id=self.account_id,
            device_id=uuid4(),
            session_id=uuid4(),
            refresh_token="test-only-token",
            refresh_family=uuid4(),
            idle_expires_at=request.now + timedelta(hours=1),
            absolute_expires_at=request.now + timedelta(hours=2),
        )


async def _authentication_context(context, *, stored_eligible, stored_state):
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    app_instance_id = uuid4()
    credential_id = b"authentication-" + uuid4().bytes
    identity = AccountIdentity(
        id=uuid4(),
        account_id=context.account.id,
        identity_type="passkey",
        provider="webauthn",
        passkey_credential_id=credential_id,
        passkey_public_key=b"verified-cose-key",
        sign_count=4,
        passkey_transports=[],
        passkey_backup_eligible=stored_eligible,
        passkey_backup_state=stored_state,
        passkey_display_name="Passkey",
        verified_at=NOW,
        is_primary=False,
        status="verified",
        identity_metadata={},
        created_at=NOW,
        updated_at=NOW,
    )
    challenge = AccountWebAuthnChallenge(
        id=uuid4(),
        ceremony_type="authentication",
        challenge_digest=hashlib.sha256(context.raw_challenge).digest(),
        device_context_digest=AccountPasskeyService._device_context_digest(
            app_instance_id, "web", public_key
        ),
        app_instance_id=app_instance_id,
        platform="web",
        device_display_name="New browser",
        rate_limit_key_digest=hashlib.sha256(uuid4().bytes).digest(),
        attempts=0,
        status="pending",
        expires_at=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )
    context.session.add_all([identity, challenge])
    await context.session.flush()
    message = passkey_module.canonical_passkey_device_message(
        authentication_challenge_id=challenge.id,
        webauthn_challenge=context.raw_challenge,
        app_instance_id=app_instance_id,
        platform="web",
        public_key=public_key,
        credential_id=credential_id,
    )
    return SimpleNamespace(
        identity=identity,
        challenge=challenge,
        private_key=private_key,
        public_key=public_key,
        app_instance_id=app_instance_id,
        credential_id=credential_id,
        signature=private_key.sign(message, ec.ECDSA(hashes.SHA256())),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_eligible", "verified_eligible", "stored_state", "verified_state"),
    [
        (False, False, False, False),
        (True, True, False, True),
        (False, True, False, True),
        (True, False, True, False),
    ],
)
async def test_authentication_enforces_immutable_backup_eligibility(
    passkey_context,
    monkeypatch,
    stored_eligible,
    verified_eligible,
    stored_state,
    verified_state,
):
    auth = await _authentication_context(
        passkey_context,
        stored_eligible=stored_eligible,
        stored_state=stored_state,
    )
    parsed = _patch_client_data(
        monkeypatch,
        registration=False,
        raw_challenge=passkey_context.raw_challenge,
    )
    parsed.raw_id = auth.credential_id
    parsed.response.user_handle = passkey_context.account.id.bytes
    monkeypatch.setattr(
        passkey_module,
        "verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(
            new_sign_count=5,
            credential_device_type=(
                CredentialDeviceType.MULTI_DEVICE
                if verified_eligible
                else CredentialDeviceType.SINGLE_DEVICE
            ),
            credential_backed_up=verified_state,
        ),
    )
    session_service = _RecordingSessionService(passkey_context.account.id)
    original_last_used = auth.identity.passkey_last_used_at
    result = await service(passkey_context).verify_authentication(
        challenge_id=auth.challenge.id,
        credential={},
        app_instance_id=auth.app_instance_id,
        platform="web",
        display_name="New browser",
        public_key=auth.public_key,
        device_signature=auth.signature,
        session_service=session_service,
        now=NOW,
    )
    if stored_eligible == verified_eligible:
        assert isinstance(result, AuthenticationVerified)
        assert session_service.calls == 1
        assert auth.identity.sign_count == 5
        assert auth.identity.passkey_backup_state is verified_state
        assert auth.identity.passkey_last_used_at == NOW
    else:
        assert isinstance(result, PasskeyRejected)
        assert vars(result) == {"attempts": 1}
        assert session_service.calls == 0
        assert auth.identity.sign_count == 4
        assert auth.identity.passkey_backup_state is stored_state
        assert auth.identity.passkey_last_used_at == original_last_used
        assert auth.challenge.status == "pending"
        assert auth.challenge.attempts == 1


class _RealUniqueViolationSessionService:
    def __init__(self, context, conflict):
        self.context = context
        self.conflict = conflict

    async def register_device_and_issue_session(self, request):
        conflicting_private_key = ec.generate_private_key(ec.SECP256R1())
        conflicting_public_key = (
            conflicting_private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        if self.conflict == "app_instance":
            app_instance_id = self.context.device.app_instance_id
            fingerprint = hashlib.sha256(conflicting_public_key).digest()
        else:
            app_instance_id = uuid4()
            fingerprint = self.context.device.public_key_fingerprint
        self.context.session.add(
            AccountDevice(
                id=uuid4(),
                account_id=self.context.account.id,
                app_instance_id=app_instance_id,
                platform="web",
                display_name="Conflicting device",
                public_key=conflicting_public_key,
                public_key_fingerprint=fingerprint,
                quick_unlock_enabled=False,
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await self.context.session.flush()
        raise AssertionError("PostgreSQL unique violation was not raised")


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", ["app_instance", "fingerprint"])
async def test_real_device_unique_violation_rejects_after_savepoint_rollback(
    passkey_context, monkeypatch, conflict
):
    auth = await _authentication_context(
        passkey_context,
        stored_eligible=False,
        stored_state=False,
    )
    parsed = _patch_client_data(
        monkeypatch,
        registration=False,
        raw_challenge=passkey_context.raw_challenge,
    )
    parsed.raw_id = auth.credential_id
    parsed.response.user_handle = passkey_context.account.id.bytes
    monkeypatch.setattr(
        passkey_module,
        "verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(
            new_sign_count=5,
            credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
            credential_backed_up=False,
        ),
    )
    before_devices = (
        await passkey_context.session.execute(
            select(func.count())
            .select_from(AccountDevice)
            .where(AccountDevice.account_id == passkey_context.account.id)
        )
    ).scalar_one()
    before_sessions = (
        await passkey_context.session.execute(
            select(func.count())
            .select_from(AccountSession)
            .where(AccountSession.account_id == passkey_context.account.id)
        )
    ).scalar_one()
    account_id = passkey_context.account.id
    challenge_id = auth.challenge.id
    result = await service(passkey_context).verify_authentication(
        challenge_id=challenge_id,
        credential={},
        app_instance_id=auth.app_instance_id,
        platform="web",
        display_name="New browser",
        public_key=auth.public_key,
        device_signature=auth.signature,
        session_service=_RealUniqueViolationSessionService(
            passkey_context, conflict
        ),
        now=NOW,
    )
    assert isinstance(result, PasskeyRejected)
    assert vars(result) == {"attempts": 1}
    assert (
        await passkey_context.session.execute(select(1))
    ).scalar_one() == 1
    passkey_context.session.expire_all()
    challenge = await passkey_context.session.get(
        AccountWebAuthnChallenge, challenge_id
    )
    assert challenge.status == "pending"
    assert challenge.attempts == 1
    assert (
            await passkey_context.session.execute(
                select(func.count())
                .select_from(AccountDevice)
                .where(AccountDevice.account_id == account_id)
            )
    ).scalar_one() == before_devices
    assert (
            await passkey_context.session.execute(
                select(func.count())
                .select_from(AccountSession)
                .where(AccountSession.account_id == account_id)
            )
    ).scalar_one() == before_sessions


async def _committed_registration_seed(setup, raw_challenge):
    account = Account(
        id=uuid4(),
        display_name="Concurrent account",
        status="active",
        security_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    setup.add(account)
    await setup.flush()
    device_key = b"concurrent-device-" + uuid4().bytes
    device = AccountDevice(
        id=uuid4(),
        account_id=account.id,
        app_instance_id=uuid4(),
        platform="web",
        display_name="Browser",
        public_key=device_key,
        public_key_fingerprint=hashlib.sha256(device_key).digest(),
        quick_unlock_enabled=False,
        status="active",
        created_at=NOW,
        updated_at=NOW,
    )
    setup.add(device)
    await setup.flush()
    account_session = AccountSession(
        id=uuid4(),
        account_id=account.id,
        device_id=device.id,
        token_selector=uuid4(),
        refresh_secret_digest=hashlib.sha256(uuid4().bytes).digest(),
        refresh_family=uuid4(),
        security_version=1,
        status="active",
        issued_at=NOW,
        idle_expires_at=NOW + timedelta(hours=1),
        absolute_expires_at=NOW + timedelta(hours=2),
        created_at=NOW,
        updated_at=NOW,
    )
    setup.add(account_session)
    await setup.flush()
    challenge = AccountWebAuthnChallenge(
        id=uuid4(),
        ceremony_type="registration",
        challenge_digest=hashlib.sha256(raw_challenge).digest(),
        account_id=account.id,
        session_id=account_session.id,
        attempts=0,
        status="pending",
        expires_at=NOW + timedelta(minutes=5),
        created_at=NOW,
        updated_at=NOW,
    )
    setup.add(challenge)
    await setup.flush()
    return account.id, account_session.id, challenge.id


@pytest.mark.asyncio
async def test_concurrent_registration_has_one_credential_winner(
    monkeypatch,
):
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first_raw = secrets.token_bytes(32)
    second_raw = secrets.token_bytes(32)
    async with sessions() as setup:
        first = await _committed_registration_seed(setup, first_raw)
        second = await _committed_registration_seed(setup, second_raw)
        await setup.commit()
    monkeypatch.setattr(
        passkey_module,
        "parse_registration_credential_json",
        lambda credential: SimpleNamespace(
            response=SimpleNamespace(
                client_data_json=credential["raw_challenge"],
                transports=[],
            )
        ),
    )
    monkeypatch.setattr(
        passkey_module,
        "parse_client_data_json",
        lambda client_data: SimpleNamespace(challenge=bytes(client_data)),
    )
    credential_id = b"shared-concurrent-" + uuid4().bytes
    monkeypatch.setattr(
        passkey_module,
        "verify_registration_response",
        lambda **_kwargs: SimpleNamespace(
            credential_id=credential_id,
            credential_public_key=b"verified-cose-key",
            sign_count=0,
            credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
            credential_backed_up=False,
        ),
    )

    async def attempt(seed, raw_challenge):
        async with sessions() as attempt_session:
            attempt_service = AccountPasskeyService(
                attempt_session,
                rp_id="restos.test",
                rp_name="RestOS",
                allowed_origins=("https://restos.test",),
                session_pepper=b"p" * 32,
                challenge_ttl=timedelta(minutes=5),
                max_verify_attempts=3,
            )
            result = await attempt_service.verify_registration(
                challenge_id=seed[2],
                account_id=seed[0],
                session_id=seed[1],
                credential={"raw_challenge": raw_challenge},
                display_name="Concurrent passkey",
                now=NOW,
            )
            await attempt_session.commit()
            return result

    results = await asyncio.gather(
        attempt(first, first_raw),
        attempt(second, second_raw),
    )
    assert sum(not isinstance(result, PasskeyRejected) for result in results) == 1
    assert sum(isinstance(result, PasskeyRejected) for result in results) == 1
    async with sessions() as verification:
        assert (
            await verification.execute(
                select(func.count())
                .select_from(AccountIdentity)
                .where(AccountIdentity.passkey_credential_id == credential_id)
            )
        ).scalar_one() == 1
        challenges = list(
            (
                await verification.execute(
                    select(AccountWebAuthnChallenge).where(
                        AccountWebAuthnChallenge.id.in_((first[2], second[2]))
                    )
                )
            ).scalars()
        )
        assert sorted(
            (challenge.status, challenge.attempts) for challenge in challenges
        ) == [("consumed", 0), ("pending", 1)]
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_authentication_has_one_new_device_winner(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    account_id = uuid4()
    app_instance_id = uuid4()
    credential_id = b"concurrent-authentication-" + uuid4().bytes
    raw_challenge = secrets.token_bytes(32)
    challenge_id = uuid4()
    async with sessions() as setup:
        setup.add(
            Account(
                id=account_id,
                display_name="Concurrent authentication",
                status="active",
                security_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await setup.flush()
        setup.add(
            AccountIdentity(
                id=uuid4(),
                account_id=account_id,
                identity_type="passkey",
                provider="webauthn",
                passkey_credential_id=credential_id,
                passkey_public_key=b"verified-cose-key",
                sign_count=0,
                passkey_transports=[],
                passkey_backup_eligible=False,
                passkey_backup_state=False,
                passkey_display_name="Passkey",
                verified_at=NOW,
                is_primary=False,
                status="verified",
                identity_metadata={},
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await setup.flush()
        setup.add(
            AccountWebAuthnChallenge(
                id=challenge_id,
                ceremony_type="authentication",
                challenge_digest=hashlib.sha256(raw_challenge).digest(),
                device_context_digest=(
                    AccountPasskeyService._device_context_digest(
                        app_instance_id, "web", public_key
                    )
                ),
                app_instance_id=app_instance_id,
                platform="web",
                device_display_name="Concurrent browser",
                rate_limit_key_digest=hashlib.sha256(uuid4().bytes).digest(),
                attempts=0,
                status="pending",
                expires_at=NOW + timedelta(minutes=5),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await setup.commit()
    monkeypatch.setattr(
        passkey_module,
        "parse_authentication_credential_json",
        lambda _credential: SimpleNamespace(
            raw_id=credential_id,
            response=SimpleNamespace(
                client_data_json=b"client-data",
                user_handle=account_id.bytes,
            ),
        ),
    )
    monkeypatch.setattr(
        passkey_module,
        "parse_client_data_json",
        lambda _client_data: SimpleNamespace(challenge=raw_challenge),
    )
    monkeypatch.setattr(
        passkey_module,
        "verify_authentication_response",
        lambda **_kwargs: SimpleNamespace(
            new_sign_count=1,
            credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
            credential_backed_up=False,
        ),
    )
    message = passkey_module.canonical_passkey_device_message(
        authentication_challenge_id=challenge_id,
        webauthn_challenge=raw_challenge,
        app_instance_id=app_instance_id,
        platform="web",
        public_key=public_key,
        credential_id=credential_id,
    )
    signature = private_key.sign(message, ec.ECDSA(hashes.SHA256()))

    async def attempt():
        async with sessions() as attempt_session:
            attempt_service = AccountPasskeyService(
                attempt_session,
                rp_id="restos.test",
                rp_name="RestOS",
                allowed_origins=("https://restos.test",),
                session_pepper=b"p" * 32,
                challenge_ttl=timedelta(minutes=5),
                max_verify_attempts=3,
            )
            result = await attempt_service.verify_authentication(
                challenge_id=challenge_id,
                credential={},
                app_instance_id=app_instance_id,
                platform="web",
                display_name="Concurrent browser",
                public_key=public_key,
                device_signature=signature,
                session_service=AccountSessionService(
                    attempt_session, b"p" * 32
                ),
                now=NOW,
            )
            await attempt_session.commit()
            return result

    results = await asyncio.gather(attempt(), attempt())
    assert sum(isinstance(result, AuthenticationVerified) for result in results) == 1
    assert sum(isinstance(result, PasskeyRejected) for result in results) == 1
    async with sessions() as verification:
        assert (
            await verification.execute(
                select(func.count())
                .select_from(AccountDevice)
                .where(AccountDevice.app_instance_id == app_instance_id)
            )
        ).scalar_one() == 1
        assert (
            await verification.execute(
                select(func.count())
                .select_from(AccountSession)
                .join(AccountDevice)
                .where(AccountDevice.app_instance_id == app_instance_id)
            )
        ).scalar_one() == 1
        challenge = await verification.get(
            AccountWebAuthnChallenge, challenge_id
        )
        assert challenge.status == "consumed"
        assert challenge.attempts == 0
    await engine.dispose()


def test_authentication_bucket_lock_key_is_stable_namespaced_signed_bigint():
    first = hashlib.sha256(b"first-test-bucket").digest()
    second = hashlib.sha256(b"second-test-bucket").digest()
    assert authentication_bucket_lock_key(first) == authentication_bucket_lock_key(
        first
    )
    assert authentication_bucket_lock_key(first) != authentication_bucket_lock_key(
        second
    )
    for key in (
        authentication_bucket_lock_key(first),
        authentication_bucket_lock_key(second),
    ):
        assert -(2**63) <= key <= 2**63 - 1
    assert _signed_bigint(b"\x80" + b"\x00" * 7) == -(2**63)
    assert _signed_bigint(b"\x7f" + b"\xff" * 7) == 2**63 - 1
    with pytest.raises(ValueError, match="bucket digest is invalid"):
        authentication_bucket_lock_key(b"raw-peer-value")


@pytest.mark.asyncio
async def test_concurrent_authentication_options_enforce_five_pending_per_bucket():
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    app_instance_id, public_key, rate_subject = authentication_context()
    bucket = authentication_bucket(app_instance_id, public_key, rate_subject)
    barrier = asyncio.Barrier(10)

    async with sessions() as before:
        before_counts_list = []
        for model in (Account, AccountDevice, AccountSession):
            result = await before.execute(select(func.count()).select_from(model))
            before_counts_list.append(result.scalar_one())
        before_counts = tuple(before_counts_list)

    async def attempt():
        async with sessions() as attempt_session:
            await barrier.wait()
            try:
                result = await service_for_session(
                    attempt_session
                ).begin_authentication(
                    app_instance_id=app_instance_id,
                    platform="web",
                    display_name="Browser",
                    public_key=public_key,
                    rate_limit_subject=rate_subject,
                    now=NOW,
                )
                await attempt_session.commit()
                return "success", result
            except AccountPasskeyRateLimited:
                await attempt_session.rollback()
                assert (
                    await attempt_session.execute(select(1))
                ).scalar_one() == 1
                return "limited", None

    async with asyncio.timeout(15):
        results = await asyncio.gather(*(attempt() for _ in range(10)))
    assert [kind for kind, _ in results].count("success") == 5
    assert [kind for kind, _ in results].count("limited") == 5

    successful = [result for kind, result in results if kind == "success"]
    async with sessions() as verification:
        rows = list(
            (
                await verification.execute(
                    select(AccountWebAuthnChallenge).where(
                        AccountWebAuthnChallenge.ceremony_type
                        == "authentication",
                        AccountWebAuthnChallenge.rate_limit_key_digest == bucket,
                        AccountWebAuthnChallenge.status == "pending",
                        AccountWebAuthnChallenge.expires_at > NOW,
                    )
                )
            ).scalars()
        )
        assert len(rows) == 5
        assert len({row.challenge_digest for row in rows}) == 5
        by_id = {row.id: row.challenge_digest for row in rows}
        for result in successful:
            encoded = result.public_key["challenge"]
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            assert hashlib.sha256(raw).digest() == by_id[result.challenge_id]
        after_counts_list = []
        for model in (Account, AccountDevice, AccountSession):
            result = await verification.execute(
                select(func.count()).select_from(model)
            )
            after_counts_list.append(result.scalar_one())
        after_counts = tuple(after_counts_list)
        assert after_counts == before_counts
    await engine.dispose()


@pytest.mark.asyncio
async def test_authentication_option_buckets_expiry_boundary_and_rollback():
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def issue(context, *, now=NOW, commit=True):
        app_instance_id, public_key, rate_subject = context
        async with sessions() as session:
            result = await service_for_session(session).begin_authentication(
                app_instance_id=app_instance_id,
                platform="web",
                display_name=None,
                public_key=public_key,
                rate_limit_subject=rate_subject,
                now=now,
            )
            if commit:
                await session.commit()
            else:
                await session.rollback()
            return result

    first = authentication_context()
    second = authentication_context()
    for _ in range(5):
        await issue(first)
        await issue(second)
    with pytest.raises(AccountPasskeyRateLimited):
        await issue(first)
    with pytest.raises(AccountPasskeyRateLimited):
        await issue(second)

    expired_context = authentication_context()
    expired_bucket = authentication_bucket(*expired_context)
    async with sessions() as setup:
        for _ in range(5):
            setup.add(
                AccountWebAuthnChallenge(
                    id=uuid4(),
                    ceremony_type="authentication",
                    challenge_digest=hashlib.sha256(uuid4().bytes).digest(),
                    account_id=None,
                    session_id=None,
                    device_context_digest=AccountPasskeyService._device_context_digest(
                        expired_context[0], "web", expired_context[1]
                    ),
                    app_instance_id=expired_context[0],
                    platform="web",
                    device_display_name=None,
                    rate_limit_key_digest=expired_bucket,
                    attempts=0,
                    status="pending",
                    expires_at=NOW - timedelta(seconds=1),
                    consumed_at=None,
                    created_at=NOW - timedelta(minutes=10),
                    updated_at=NOW - timedelta(minutes=10),
                )
            )
        await setup.commit()
    await issue(expired_context)

    boundary = authentication_context()
    for _ in range(4):
        await issue(boundary)
    await issue(boundary)
    with pytest.raises(AccountPasskeyRateLimited):
        await issue(boundary)

    rolled_back = authentication_context()
    await issue(rolled_back, commit=False)
    for _ in range(5):
        await issue(rolled_back)
    with pytest.raises(AccountPasskeyRateLimited):
        await issue(rolled_back)
    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_options_keep_account_serialization(passkey_context):
    for _ in range(5):
        await service(passkey_context).begin_registration(
            passkey_context.account.id,
            passkey_context.account_session.id,
            NOW,
        )
    with pytest.raises(AccountPasskeyRateLimited):
        await service(passkey_context).begin_registration(
            passkey_context.account.id,
            passkey_context.account_session.id,
            NOW,
        )
