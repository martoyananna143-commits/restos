"""PostgreSQL integration tests for SMS phone verification foundation."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.account import Account
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.internal.services.phone_verification_service import (
    InvalidOrUnavailablePhoneChallenge,
    InvalidPhoneVerificationRequest,
    PhoneVerificationCodeRequested,
    PhoneVerificationCooldown,
    PhoneVerificationRejected,
    PhoneVerificationService,
    PhoneVerificationSucceeded,
    RequestPhoneVerificationCode,
    SmsDeliveryFailed,
    VerifyPhoneVerificationCode,
)


NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)
PHONE_PEPPER = b"phone-pepper-for-restos-tests!!!"
CODE_PEPPER = b"code-pepper-for-restos-tests!!!!"


class FakeSmsSender:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    async def send_verification_code(
        self, phone, code, purpose, expires_in_seconds, autofill_domain
    ):
        if self.fail:
            raise RuntimeError("provider unavailable")
        self.messages.append({
            "phone": phone, "code": code, "purpose": purpose,
            "expires_in_seconds": expires_in_seconds,
            "autofill_domain": autofill_domain,
            "text": f"Код подтверждения RestOS: {code}\n\n@{autofill_domain} #{code}",
        })


class Codes:
    def __init__(self, *codes):
        self.codes = iter(codes)

    def __call__(self):
        return next(self.codes)


@pytest_asyncio.fixture
async def phone_context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    account = Account(
        id=uuid4(), display_name="Phone account", status="active",
        security_version=1,
    )
    session.add(account)
    await session.flush()
    try:
        yield session, account
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def service(session, sender=None, codes=("012345",)):
    sender = sender or FakeSmsSender()
    return PhoneVerificationService(
        session=session,
        sender=sender,
        phone_pepper=PHONE_PEPPER,
        code_pepper=CODE_PEPPER,
        autofill_domain="restos.app",
        code_generator=Codes(*codes),
    ), sender


def request(account, now=NOW, phone="+7 (999) 123-45-67"):
    return RequestPhoneVerificationCode(
        purpose="login", phone=phone, now=now, account_id=account.id
    )


@pytest.mark.asyncio
async def test_request_normalizes_e164_sends_leading_zero_and_stores_only_hmac(
    phone_context,
):
    session, account = phone_context
    verification, sender = service(session)
    result = await verification.request_code(request(account))
    stored = await session.get(PhoneVerificationChallenge, result.challenge_id)
    message = sender.messages[0]
    normalized = "+79991234567"
    phone_digest = hmac.new(
        PHONE_PEPPER, normalized.encode("ascii"), hashlib.sha256
    ).digest()
    expected_code_digest = hmac.new(
        CODE_PEPPER,
        stored.id.bytes + b"login" + phone_digest + b"012345",
        hashlib.sha256,
    ).digest()
    assert isinstance(result, PhoneVerificationCodeRequested)
    assert message["phone"] == normalized and message["code"] == "012345"
    assert message["autofill_domain"] == "restos.app"
    assert message["text"] == "Код подтверждения RestOS: 012345\n\n@restos.app #012345"
    assert stored.phone_digest == phone_digest
    assert stored.code_digest == expected_code_digest
    assert stored.status == "pending" and stored.attempts_used == 0
    assert not hasattr(stored, "phone") and not hasattr(stored, "code")


@pytest.mark.parametrize("phone,expected", [
    ("+79991234567", "+79991234567"),
    (" +7 (999) 123-45-67 ", "+79991234567"),
    ("89991234567", "+79991234567"),
    ("+12025550123", "+12025550123"),
])
def test_e164_normalization(phone, expected):
    assert PhoneVerificationService.normalize_e164(phone) == expected


@pytest.mark.parametrize("phone", ["+09991234567", "+123", "+1234567890123456", "١٢٣"])
def test_invalid_e164_is_rejected(phone):
    with pytest.raises(InvalidPhoneVerificationRequest):
        PhoneVerificationService.normalize_e164(phone)


@pytest.mark.asyncio
async def test_different_challenges_bind_code_to_id(phone_context):
    session, account = phone_context
    verification, _ = service(session, codes=("012345", "012345"))
    first = await verification.request_code(request(account))
    first_row = await session.get(PhoneVerificationChallenge, first.challenge_id)
    first_row.status = "cancelled"
    first_row.cancelled_at = NOW + timedelta(minutes=1)
    await session.flush()
    second = await verification.request_code(
        request(account, now=NOW + timedelta(minutes=1))
    )
    second_row = await session.get(PhoneVerificationChallenge, second.challenge_id)
    assert first_row.code_digest != second_row.code_digest


@pytest.mark.asyncio
async def test_cooldown_and_resend_cancel_old_pending(phone_context):
    session, account = phone_context
    verification, sender = service(session, codes=("012345", "123456"))
    first = await verification.request_code(request(account))
    with pytest.raises(PhoneVerificationCooldown):
        await verification.request_code(
            request(account, now=NOW + timedelta(seconds=59))
        )
    second = await verification.request_code(
        request(account, now=NOW + timedelta(seconds=60))
    )
    old = await session.get(PhoneVerificationChallenge, first.challenge_id)
    assert old.status == "cancelled" and old.cancelled_at == NOW + timedelta(seconds=60)
    assert second.challenge_id != first.challenge_id and len(sender.messages) == 2


@pytest.mark.asyncio
async def test_expired_pending_is_closed_before_new_request(phone_context):
    session, account = phone_context
    verification, _ = service(session, codes=("012345", "123456"))
    first = await verification.request_code(request(account))
    second = await verification.request_code(
        request(account, now=NOW + timedelta(minutes=5))
    )
    old = await session.get(PhoneVerificationChallenge, first.challenge_id)
    assert old.status == "expired" and second.challenge_id != first.challenge_id


@pytest.mark.asyncio
async def test_sms_failure_rolls_back_new_challenge_and_outer_transaction_works(
    phone_context,
):
    session, account = phone_context
    verification, _ = service(session, sender=FakeSmsSender(fail=True))
    count_before = (
        await session.execute(
            select(func.count()).select_from(PhoneVerificationChallenge)
        )
    ).scalar_one()
    with pytest.raises(SmsDeliveryFailed):
        await verification.request_code(request(account))
    assert (
        await session.execute(
            select(func.count()).select_from(PhoneVerificationChallenge)
        )
    ).scalar_one() == count_before
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_successful_verification_is_one_time_and_safe(phone_context, monkeypatch):
    session, account = phone_context
    verification, _ = service(session)
    issued = await verification.request_code(request(account))
    compared = []
    original = hmac.compare_digest
    monkeypatch.setattr(
        "app.internal.services.phone_verification_service.hmac.compare_digest",
        lambda left, right: compared.append(True) or original(left, right),
    )
    result = await verification.verify_code(VerifyPhoneVerificationCode(
        issued.challenge_id, "+79991234567", "012345", NOW + timedelta(seconds=10)
    ))
    assert isinstance(result, PhoneVerificationSucceeded) and compared
    assert result.account_id == account.id and result.purpose == "login"
    assert not hasattr(result, "code") and not hasattr(result, "phone_digest")
    with pytest.raises(InvalidOrUnavailablePhoneChallenge):
        await verification.verify_code(VerifyPhoneVerificationCode(
            issued.challenge_id, "+79991234567", "012345", NOW + timedelta(seconds=11)
        ))


@pytest.mark.asyncio
async def test_wrong_attempts_increment_and_last_attempt_locks(phone_context):
    session, account = phone_context
    verification, _ = service(session)
    issued = await verification.request_code(request(account))
    for attempt in range(1, 6):
        rejected = await verification.verify_code(VerifyPhoneVerificationCode(
            issued.challenge_id, "+79991234567", "999999",
            NOW + timedelta(seconds=attempt),
        ))
        assert isinstance(rejected, PhoneVerificationRejected)
        assert rejected.attempts_remaining == 5 - attempt
    stored = await session.get(PhoneVerificationChallenge, issued.challenge_id)
    assert stored.status == "locked" and stored.locked_at == NOW + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_expiry_is_persisted_without_exception(phone_context):
    session, account = phone_context
    verification, _ = service(session)
    issued = await verification.request_code(request(account))
    result = await verification.verify_code(VerifyPhoneVerificationCode(
        issued.challenge_id, "+79991234567", "012345", NOW + timedelta(minutes=5)
    ))
    stored = await session.get(PhoneVerificationChallenge, issued.challenge_id)
    assert isinstance(result, PhoneVerificationRejected) and result.reason == "expired"
    assert stored.status == "expired"


@pytest.mark.asyncio
async def test_wrong_phone_is_unavailable_without_attempt_increment(phone_context):
    session, account = phone_context
    verification, _ = service(session)
    issued = await verification.request_code(request(account))
    with pytest.raises(InvalidOrUnavailablePhoneChallenge):
        await verification.verify_code(VerifyPhoneVerificationCode(
            issued.challenge_id, "+79990000000", "012345", NOW
        ))
    stored = await session.get(PhoneVerificationChallenge, issued.challenge_id)
    assert stored.attempts_used == 0 and stored.status == "pending"
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_unknown_context_is_generic(phone_context):
    session, _ = phone_context
    verification, _ = service(session)
    with pytest.raises(Exception) as caught:
        await verification.request_code(RequestPhoneVerificationCode(
            purpose="login", phone="+79991234567", now=NOW, account_id=uuid4()
        ))
    assert caught.type.__name__ == "PhoneVerificationUnavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("phone_digest", b"x" * 31),
    ("code_digest", b"x" * 33),
    ("purpose", "bad"),
    ("status", "bad"),
    ("max_attempts", 0),
    ("attempts_used", 6),
])
async def test_database_rejects_invalid_challenges(phone_context, field, value):
    session, account = phone_context
    values = dict(
        id=uuid4(), account_id=account.id, invitation_id=None,
        employee_profile_id=None, purpose="login", phone_digest=b"p" * 32,
        code_digest=b"c" * 32, status="pending", attempts_used=0,
        max_attempts=5, expires_at=NOW + timedelta(minutes=5),
        resend_available_at=NOW + timedelta(minutes=1), verified_at=None,
        locked_at=None, cancelled_at=None, created_at=NOW, updated_at=NOW,
    )
    values[field] = value
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(PhoneVerificationChallenge(**values))
            await session.flush()
    assert (await session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_digest_columns_are_physical_bytea(phone_context):
    session, _ = phone_context
    rows = (await session.execute(text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'phone_verification_challenges' "
        "AND column_name IN ('phone_digest', 'code_digest') ORDER BY column_name"
    ))).all()
    assert rows == [("code_digest", "bytea"), ("phone_digest", "bytea")]


@pytest.mark.asyncio
async def test_unknown_integrity_error_is_not_masked(phone_context, monkeypatch):
    session, account = phone_context
    verification, _ = service(session)

    async def fail(_):
        raise IntegrityError("select", {}, RuntimeError("unrelated"))

    monkeypatch.setattr(verification, "_validate_context", fail)
    with pytest.raises(IntegrityError):
        await verification.request_code(request(account))


@pytest.mark.asyncio
async def test_concurrent_requests_leave_one_pending_challenge():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    account_id = uuid4()
    phone = f"+7999{uuid4().int % 10_000_000:07d}"
    async with AsyncSession(engine) as setup:
        setup.add(Account(
            id=account_id, display_name="Concurrent phone", status="active",
            security_version=1,
        ))
        await setup.commit()

    async def issue(code):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            sender = FakeSmsSender()
            verification = PhoneVerificationService(
                session, sender, PHONE_PEPPER, CODE_PEPPER, "restos.app",
                code_generator=Codes(code),
            )
            async with session.begin():
                return await verification.request_code(RequestPhoneVerificationCode(
                    "login", phone, NOW, account_id=account_id
                ))

    results = await asyncio.gather(
        issue("012345"), issue("123456"), return_exceptions=True
    )
    assert sum(isinstance(item, PhoneVerificationCodeRequested) for item in results) == 1
    assert sum(isinstance(item, PhoneVerificationCooldown) for item in results) == 1
    async with AsyncSession(engine) as verify:
        count = (await verify.execute(
            select(func.count()).select_from(PhoneVerificationChallenge).where(
                PhoneVerificationChallenge.status == "pending",
                PhoneVerificationChallenge.purpose == "login",
                PhoneVerificationChallenge.phone_digest
                == hmac.new(
                    PHONE_PEPPER, phone.encode("ascii"), hashlib.sha256
                ).digest(),
            )
        )).scalar_one()
        assert count == 1
    await engine.dispose()
