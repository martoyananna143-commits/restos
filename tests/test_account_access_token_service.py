"""PostgreSQL integration tests for Account access-token validation."""

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

from jose import jwt
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.account import Account, AccountDevice, AccountSession
from app.internal.services.account_access_token_service import (
    AccountAccessTokenConfigurationError,
    AccountAccessTokenRejected,
    AccountAccessTokenService,
    InvalidAccountAccessTokenRequest,
    IssueAccountAccessToken,
    VerifyAccountAccessToken,
)


KEY = b"account-access-token-test-key!!" + b"x" * 8
OTHER_KEY = b"other-account-access-token-key!" + b"y" * 8


@pytest_asyncio.fixture
async def context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    account = Account(
        id=uuid4(), display_name="Account", status="active", security_version=3,
        created_at=now, updated_at=now,
    )
    session.add(account)
    await session.flush()
    device = AccountDevice(
        id=uuid4(), account_id=account.id, app_instance_id=uuid4(),
        platform="ios", display_name="iPhone", public_key=b"public-key",
        public_key_fingerprint=b"f" * 32, quick_unlock_enabled=False,
        status="active", last_seen_at=now, revoked_at=None, revoked_reason=None,
        created_at=now, updated_at=now,
    )
    session.add(device)
    await session.flush()
    account_session = AccountSession(
        id=uuid4(), account_id=account.id, device_id=device.id,
        token_selector=uuid4(), refresh_secret_digest=b"d" * 32,
        refresh_family=uuid4(), previous_rotated_session_id=None,
        security_version=account.security_version, status="active",
        issued_at=now - timedelta(minutes=1), last_used_at=None,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(hours=2),
        revoked_at=None, revoked_reason=None, created_at=now, updated_at=now,
    )
    session.add(account_session)
    await session.flush()
    value = SimpleNamespace(
        engine=engine, connection=connection, transaction=transaction,
        session=session, now=now, account=account, device=device,
        account_session=account_session,
    )
    try:
        yield value
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def service(context, *, key=KEY, ttl=timedelta(minutes=10)):
    return AccountAccessTokenService(context.session, key, ttl)


async def issued(context, **changes):
    values = {
        "account_id": context.account.id,
        "session_id": context.account_session.id,
        "device_id": context.device.id,
        "now": context.now,
    }
    values.update(changes)
    return await service(context).issue(IssueAccountAccessToken(**values))


def claims(context, **changes):
    values = {
        "sub": str(context.account.id),
        "sid": str(context.account_session.id),
        "did": str(context.device.id),
        "sv": context.account.security_version,
        "iat": int(context.now.timestamp()),
        "nbf": int(context.now.timestamp()),
        "exp": int((context.now + timedelta(minutes=5)).timestamp()),
        "iss": "restos-account-auth",
        "aud": "restos-api",
        "typ": "access",
    }
    values.update(changes)
    return values


@pytest.mark.asyncio
async def test_issue_and_verify_claims_without_database_mutation(context):
    result = await issued(context)
    unverified = jwt.get_unverified_claims(result.access_token)
    assert unverified == claims(
        context, exp=int(result.expires_at.timestamp())
    )
    principal = await service(context).verify(
        VerifyAccountAccessToken(result.access_token, context.now)
    )
    assert principal.account_id == context.account.id
    assert principal.session_id == context.account_session.id
    assert principal.device_id == context.device.id
    assert principal.security_version == 3
    assert principal.token_expires_at == result.expires_at
    assert not context.session.new and not context.session.dirty


@pytest.mark.asyncio
async def test_issue_ttl_is_capped_by_session_absolute_expiry(context):
    short_expiry = context.now + timedelta(seconds=30)
    context.account_session.idle_expires_at = short_expiry
    context.account_session.absolute_expires_at = short_expiry
    await context.session.flush()
    result = await service(context, ttl=timedelta(minutes=10)).issue(
        IssueAccountAccessToken(
            context.account.id, context.account_session.id, context.device.id,
            context.now,
        )
    )
    token_claims = jwt.get_unverified_claims(result.access_token)
    assert result.access_token
    assert result.expires_at == short_expiry
    assert datetime.fromtimestamp(token_claims["exp"], timezone.utc) <= short_expiry
    assert result.expires_at < context.now + timedelta(minutes=10)
    assert context.account_session.idle_expires_at == short_expiry
    assert context.account_session.absolute_expires_at == short_expiry


@pytest.mark.parametrize("key", [b"", b"x" * 31, "not-bytes"])
def test_configuration_requires_32_byte_key(key):
    with pytest.raises(AccountAccessTokenConfigurationError):
        AccountAccessTokenService(None, key)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"account_id": "bad"},
        {"session_id": "bad"},
        {"device_id": "bad"},
        {"now": datetime.now()},
    ],
)
async def test_issue_runtime_validation_precedes_sql(context, change):
    values = {
        "account_id": context.account.id,
        "session_id": context.account_session.id,
        "device_id": context.device.id,
        "now": context.now,
    }
    values.update(change)
    with pytest.raises(InvalidAccountAccessTokenRequest):
        await service(context).issue(IssueAccountAccessToken(**values))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    ["", "not-a-jwt"],
)
async def test_malformed_token_is_rejected(context, token):
    error = InvalidAccountAccessTokenRequest if not token else AccountAccessTokenRejected
    with pytest.raises(error):
        await service(context).verify(VerifyAccountAccessToken(token, context.now))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("algorithm", "key", "change"),
    [
        ("HS256", OTHER_KEY, {}),
        ("HS512", KEY, {}),
        ("HS256", KEY, {"iss": "other"}),
        ("HS256", KEY, {"aud": "other"}),
        ("HS256", KEY, {"typ": "refresh"}),
        ("HS256", KEY, {"sub": "not-uuid"}),
        ("HS256", KEY, {"sv": 0}),
        ("HS256", KEY, {"nbf": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())}),
        ("HS256", KEY, {"exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())}),
    ],
)
async def test_invalid_crypto_or_claims_are_rejected(
    context, algorithm, key, change
):
    token = jwt.encode(claims(context, **change), key, algorithm=algorithm)
    with pytest.raises(AccountAccessTokenRejected):
        await service(context).verify(VerifyAccountAccessToken(token, context.now))


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["sub", "sid", "did", "sv", "iat", "nbf", "exp"])
async def test_missing_claim_is_rejected(context, missing):
    values = claims(context)
    values.pop(missing)
    token = jwt.encode(values, KEY, algorithm="HS256")
    with pytest.raises(AccountAccessTokenRejected):
        await service(context).verify(VerifyAccountAccessToken(token, context.now))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "value"),
    [
        ("account.status", "suspended"),
        ("account.status", "disabled"),
        ("account.deleted_at", "now"),
        ("account.security_version", 4),
        ("device.status", "disabled"),
        ("device.status", "revoked"),
        ("session.status", "rotated"),
        ("session.status", "revoked"),
        ("session.status", "expired"),
        ("session.status", "compromised"),
        ("session.idle_expires_at", "past"),
        ("session.absolute_expires_at", "past"),
    ],
)
async def test_database_revocation_state_rejects_token(context, target, value):
    token = (await issued(context)).access_token
    object_name, attribute = target.split(".")
    obj = {
        "account": context.account,
        "device": context.device,
        "session": context.account_session,
    }[object_name]
    if value == "now":
        value = context.now
    if value == "past":
        value = context.now - timedelta(seconds=1)
    if target == "session.absolute_expires_at":
        context.account_session.idle_expires_at = value
    setattr(obj, attribute, value)
    if target == "device.status" and value == "revoked":
        context.device.revoked_at = context.now
    if target == "session.status" and value in {"revoked", "compromised"}:
        context.account_session.revoked_at = context.now
    await context.session.flush()
    with pytest.raises(AccountAccessTokenRejected):
        await service(context).verify(VerifyAccountAccessToken(token, context.now))


@pytest.mark.asyncio
async def test_cross_device_claim_is_rejected(context):
    token = jwt.encode(claims(context, did=str(uuid4())), KEY, algorithm="HS256")
    with pytest.raises(AccountAccessTokenRejected):
        await service(context).verify(VerifyAccountAccessToken(token, context.now))
