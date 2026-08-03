"""PostgreSQL integration tests for AccountDevice and AccountSession service."""

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
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.account import Account, AccountDevice, AccountSession
from app.internal.services.account_session_service import (
    AccountSessionService,
    AccountUnavailableForSession,
    DeviceIdentityMismatch,
    DeviceUnavailableForSession,
    InvalidAccountSessionRequest,
    InvalidRefreshSession,
    RefreshRejected,
    RegisterDeviceAndIssueSession,
    RevokeAllAccountSessions,
    RevokeDeviceSessions,
    RotateRefreshSession,
    RotatedRefreshSession,
)


NOW = datetime(2026, 7, 23, 13, 0, tzinfo=timezone.utc)
PEPPER = b"session-pepper-for-restos-tests!!"
SECRET = b"a" * 32


class Values:
    def __init__(self, *values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


@pytest_asyncio.fixture
async def session_context():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    account = Account(
        id=uuid4(), display_name="Account", status="active", security_version=1
    )
    other = Account(
        id=uuid4(), display_name="Other", status="active", security_version=1
    )
    session.add_all([account, other])
    await session.flush()
    ctx = SimpleNamespace(
        engine=engine, connection=connection, transaction=transaction,
        session=session, account=account, other=other,
    )
    try:
        yield ctx
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


def registration(ctx, **changes):
    values = dict(
        account_id=ctx.account.id,
        app_instance_id=uuid4(),
        platform="ios",
        display_name="Anna's iPhone",
        public_key=b"public-key-one",
        now=NOW,
    )
    values.update(changes)
    return RegisterDeviceAndIssueSession(**values)


def make_service(ctx, selectors=(), secrets=(), **changes):
    kwargs = dict(session=ctx.session, pepper=PEPPER)
    if selectors:
        kwargs["selector_generator"] = Values(*selectors)
    if secrets:
        kwargs["secret_generator"] = Values(*secrets)
    kwargs.update(changes)
    return AccountSessionService(**kwargs)


def decode_token(token):
    selector_text, secret_text = token.split(".")
    secret = base64.urlsafe_b64decode(secret_text + "=" * (-len(secret_text) % 4))
    return UUID(selector_text), secret


@pytest.mark.asyncio
async def test_registration_creates_device_and_hmac_only_session(session_context):
    ctx = session_context
    selector = uuid4()
    result = await make_service(
        ctx, selectors=(selector,), secrets=(SECRET,)
    ).register_device_and_issue_session(registration(ctx))
    device = await ctx.session.get(AccountDevice, result.device_id)
    stored = await ctx.session.get(AccountSession, result.session_id)
    parsed_selector, parsed_secret = decode_token(result.refresh_token)

    assert parsed_selector == selector and parsed_secret == SECRET
    assert device.public_key_fingerprint == hashlib.sha256(b"public-key-one").digest()
    assert device.public_key == b"public-key-one"
    assert device.status == "active" and device.quick_unlock_enabled is False
    assert stored.refresh_secret_digest == hmac.new(
        PEPPER, selector.bytes + SECRET, hashlib.sha256
    ).digest()
    assert stored.refresh_family == result.refresh_family
    assert stored.previous_rotated_session_id is None
    assert stored.security_version == 1 and stored.status == "active"
    assert stored.last_used_at is None
    assert stored.idle_expires_at == NOW + timedelta(days=30)
    assert stored.absolute_expires_at == NOW + timedelta(days=90)
    assert not hasattr(stored, "refresh_token") and not hasattr(stored, "secret")


@pytest.mark.asyncio
async def test_same_app_and_key_reuses_device_but_issues_new_session(session_context):
    ctx = session_context
    app_id = uuid4()
    service = make_service(ctx)
    first = await service.register_device_and_issue_session(
        registration(ctx, app_instance_id=app_id)
    )
    second = await service.register_device_and_issue_session(
        registration(ctx, app_instance_id=app_id, now=NOW + timedelta(minutes=1))
    )
    assert first.device_id == second.device_id
    assert first.session_id != second.session_id
    device = await ctx.session.get(AccountDevice, first.device_id)
    assert device.last_seen_at == NOW + timedelta(minutes=1)


@pytest.mark.asyncio
async def test_same_app_with_other_key_is_rejected(session_context):
    ctx = session_context
    app_id = uuid4()
    service = make_service(ctx)
    await service.register_device_and_issue_session(
        registration(ctx, app_instance_id=app_id)
    )
    with pytest.raises(DeviceIdentityMismatch):
        await service.register_device_and_issue_session(
            registration(ctx, app_instance_id=app_id, public_key=b"other-key")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["revoked", "disabled"])
async def test_revoked_or_disabled_device_is_not_reactivated(session_context, status):
    ctx = session_context
    app_id = uuid4()
    first = await make_service(ctx).register_device_and_issue_session(
        registration(ctx, app_instance_id=app_id)
    )
    device = await ctx.session.get(AccountDevice, first.device_id)
    device.status = status
    device.revoked_at = NOW if status == "revoked" else None
    await ctx.session.flush()
    with pytest.raises(DeviceUnavailableForSession):
        await make_service(ctx).register_device_and_issue_session(
            registration(ctx, app_instance_id=app_id)
        )
    assert device.status == status


@pytest.mark.asyncio
@pytest.mark.parametrize("status,deleted", [
    ("suspended", False), ("disabled", False), ("active", True),
])
async def test_unavailable_account_cannot_register(session_context, status, deleted):
    ctx = session_context
    ctx.account.status = status
    ctx.account.deleted_at = NOW if deleted else None
    await ctx.session.flush()
    with pytest.raises(AccountUnavailableForSession):
        await make_service(ctx).register_device_and_issue_session(registration(ctx))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"public_key": b""},
    {"public_key": "not-bytes"},
    {"platform": "watchos"},
    {"platform": 1},
    {"display_name": 1},
    {"display_name": "x" * 256},
    {"now": datetime(2026, 7, 23, 13, 0)},
])
async def test_invalid_registration_input_is_rejected(session_context, change):
    before_devices = (
        await session_context.session.execute(
            select(func.count()).select_from(AccountDevice)
        )
    ).scalar_one()
    before_sessions = (
        await session_context.session.execute(
            select(func.count()).select_from(AccountSession)
        )
    ).scalar_one()
    with pytest.raises(InvalidAccountSessionRequest):
        await make_service(session_context).register_device_and_issue_session(
            registration(session_context, **change)
        )
    assert (
        await session_context.session.execute(
            select(func.count()).select_from(AccountDevice)
        )
    ).scalar_one() == before_devices
    assert (
        await session_context.session.execute(
            select(func.count()).select_from(AccountSession)
        )
    ).scalar_one() == before_sessions
    assert (await session_context.session.execute(select(1))).scalar_one() == 1


def test_invalid_pepper_and_ttl_are_rejected():
    with pytest.raises(ValueError):
        AccountSessionService(None, b"short")
    with pytest.raises(ValueError):
        AccountSessionService(None, PEPPER, idle_ttl=timedelta(0))
    with pytest.raises(ValueError):
        AccountSessionService(
            None, PEPPER, idle_ttl=timedelta(days=91),
            absolute_ttl=timedelta(days=90),
        )


@pytest.mark.asyncio
async def test_global_fingerprint_conflict_is_not_masked(session_context):
    ctx = session_context
    await make_service(ctx).register_device_and_issue_session(registration(ctx))
    with pytest.raises(IntegrityError):
        await make_service(ctx).register_device_and_issue_session(
            registration(ctx, account_id=ctx.other.id, app_instance_id=uuid4())
        )


@pytest.mark.asyncio
async def test_active_refresh_rotates_without_extending_absolute_expiry(session_context):
    ctx = session_context
    selectors = (uuid4(), uuid4())
    service = make_service(
        ctx, selectors=selectors, secrets=(b"a" * 32, b"b" * 32)
    )
    issued = await service.register_device_and_issue_session(registration(ctx))
    rotated = await service.rotate_refresh_session(RotateRefreshSession(
        issued.refresh_token, NOW + timedelta(days=20)
    ))
    assert isinstance(rotated, RotatedRefreshSession)
    old = await ctx.session.get(AccountSession, issued.session_id)
    new = await ctx.session.get(AccountSession, rotated.session_id)
    assert old.status == "rotated" and old.last_used_at == NOW + timedelta(days=20)
    assert new.previous_rotated_session_id == old.id
    assert new.refresh_family == old.refresh_family
    assert new.absolute_expires_at == old.absolute_expires_at
    assert new.idle_expires_at == NOW + timedelta(days=50)
    assert rotated.refresh_token != issued.refresh_token


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "not-a-token", "00000000-0000-0000-0000-000000000000.x", "x.y.z"])
async def test_malformed_refresh_is_rejected(session_context, token):
    with pytest.raises(InvalidRefreshSession):
        await make_service(session_context).rotate_refresh_session(
            RotateRefreshSession(token, NOW)
        )


@pytest.mark.asyncio
async def test_unknown_selector_and_wrong_secret_do_not_change_family(session_context):
    ctx = session_context
    issued = await make_service(ctx).register_device_and_issue_session(registration(ctx))
    unknown = f"{uuid4()}." + base64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode()
    with pytest.raises(InvalidRefreshSession):
        await make_service(ctx).rotate_refresh_session(RotateRefreshSession(unknown, NOW))
    selector, _ = decode_token(issued.refresh_token)
    wrong = f"{selector}." + base64.urlsafe_b64encode(b"z" * 32).rstrip(b"=").decode()
    with pytest.raises(InvalidRefreshSession):
        await make_service(ctx).rotate_refresh_session(RotateRefreshSession(wrong, NOW))
    stored = await ctx.session.get(AccountSession, issued.session_id)
    assert stored.status == "active"


@pytest.mark.asyncio
async def test_reuse_compromises_active_family_and_new_token(session_context):
    ctx = session_context
    service = make_service(ctx)
    issued = await service.register_device_and_issue_session(registration(ctx))
    rotated = await service.rotate_refresh_session(
        RotateRefreshSession(issued.refresh_token, NOW + timedelta(days=1))
    )
    rejected = await service.rotate_refresh_session(
        RotateRefreshSession(issued.refresh_token, NOW + timedelta(days=2))
    )
    assert isinstance(rejected, RefreshRejected)
    assert rejected.reason == "refresh_token_reuse" and rejected.requires_full_login
    active = await ctx.session.get(AccountSession, rotated.session_id)
    assert active.status == "compromised"
    assert active.revoked_reason == "refresh_token_reuse"
    retry = await service.rotate_refresh_session(
        RotateRefreshSession(rotated.refresh_token, NOW + timedelta(days=2))
    )
    assert isinstance(retry, RefreshRejected) and retry.reason == "compromised"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "account_suspended", "account_deleted", "device_revoked", "device_disabled",
    "security_version", "idle_expired", "absolute_expired", "session_revoked",
    "session_compromised", "session_expired",
])
async def test_refresh_rejection_conditions(session_context, case):
    ctx = session_context
    issued = await make_service(ctx).register_device_and_issue_session(registration(ctx))
    stored = await ctx.session.get(AccountSession, issued.session_id)
    device = await ctx.session.get(AccountDevice, issued.device_id)
    now = NOW + timedelta(minutes=1)
    if case == "account_suspended":
        ctx.account.status = "suspended"
    elif case == "account_deleted":
        ctx.account.deleted_at = NOW
    elif case == "device_revoked":
        device.status, device.revoked_at = "revoked", NOW
    elif case == "device_disabled":
        device.status = "disabled"
    elif case == "security_version":
        ctx.account.security_version += 1
    elif case == "idle_expired":
        now = stored.idle_expires_at
    elif case == "absolute_expired":
        now = stored.absolute_expires_at
    else:
        stored.status = case.removeprefix("session_")
        if stored.status in {"revoked", "compromised"}:
            stored.revoked_at = NOW
    await ctx.session.flush()
    result = await make_service(ctx).rotate_refresh_session(
        RotateRefreshSession(issued.refresh_token, now)
    )
    assert isinstance(result, RefreshRejected) and result.requires_full_login


@pytest.mark.asyncio
async def test_revoke_device_only_revokes_its_active_sessions(session_context):
    ctx = session_context
    service = make_service(ctx)
    first = await service.register_device_and_issue_session(registration(ctx))
    second = await service.register_device_and_issue_session(
        registration(ctx, app_instance_id=uuid4(), public_key=b"public-key-two")
    )
    first_device = await ctx.session.get(AccountDevice, first.device_id)
    first_device.quick_unlock_enabled = True
    result = await service.revoke_device_sessions(RevokeDeviceSessions(
        actor_account_id=ctx.account.id, target_account_id=ctx.account.id,
        device_id=first.device_id, now=NOW + timedelta(hours=1), reason="lost",
    ))
    assert result.revoked_session_count == 1
    assert first_device.status == "revoked" and first_device.quick_unlock_enabled is False
    assert (await ctx.session.get(AccountSession, first.session_id)).status == "revoked"
    assert (await ctx.session.get(AccountSession, second.session_id)).status == "active"
    again = await service.revoke_device_sessions(RevokeDeviceSessions(
        ctx.account.id, ctx.account.id, first.device_id,
        NOW + timedelta(hours=2), "repeat",
    ))
    assert again.revoked_session_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"actor_account_id": "not-uuid"},
    {"target_account_id": "not-uuid"},
    {"device_id": "not-uuid"},
    {"now": datetime(2026, 7, 23, 13, 0)},
    {"reason": 123},
    {"reason": ""},
    {"reason": "   "},
    {"reason": "x" * 501},
])
async def test_invalid_revoke_device_input_is_controlled_and_has_no_sql_changes(
    session_context, change,
):
    ctx = session_context
    issued = await make_service(ctx).register_device_and_issue_session(registration(ctx))
    values = dict(
        actor_account_id=ctx.account.id,
        target_account_id=ctx.account.id,
        device_id=issued.device_id,
        now=NOW,
        reason="lost",
    )
    values.update(change)
    device = await ctx.session.get(AccountDevice, issued.device_id)
    stored = await ctx.session.get(AccountSession, issued.session_id)
    with pytest.raises(InvalidAccountSessionRequest):
        await make_service(ctx).revoke_device_sessions(RevokeDeviceSessions(**values))
    await ctx.session.refresh(device)
    await ctx.session.refresh(stored)
    assert device.status == "active" and device.revoked_at is None
    assert stored.status == "active" and stored.revoked_at is None
    assert (await ctx.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_revoke_device_reason_is_stripped_before_storage(session_context):
    ctx = session_context
    issued = await make_service(ctx).register_device_and_issue_session(registration(ctx))
    await make_service(ctx).revoke_device_sessions(RevokeDeviceSessions(
        ctx.account.id, ctx.account.id, issued.device_id, NOW, "  lost phone  "
    ))
    device = await ctx.session.get(AccountDevice, issued.device_id)
    assert device.revoked_reason == "lost phone"


@pytest.mark.asyncio
async def test_cannot_revoke_other_accounts_device(session_context):
    ctx = session_context
    issued = await make_service(ctx).register_device_and_issue_session(registration(ctx))
    with pytest.raises(DeviceUnavailableForSession):
        await make_service(ctx).revoke_device_sessions(RevokeDeviceSessions(
            ctx.other.id, ctx.account.id, issued.device_id, NOW, "not mine"
        ))


@pytest.mark.asyncio
async def test_revoke_all_increments_version_and_allows_full_login_again(session_context):
    ctx = session_context
    service = make_service(ctx)
    first = await service.register_device_and_issue_session(registration(ctx))
    device = await ctx.session.get(AccountDevice, first.device_id)
    device.quick_unlock_enabled = True
    result = await service.revoke_all_account_sessions(
        RevokeAllAccountSessions(ctx.account.id, NOW + timedelta(hours=1))
    )
    assert result.security_version == 2 and result.revoked_session_count == 1
    assert device.status == "active" and device.quick_unlock_enabled is False
    assert (await ctx.session.get(AccountSession, first.session_id)).status == "revoked"
    retry = await service.rotate_refresh_session(
        RotateRefreshSession(first.refresh_token, NOW + timedelta(hours=2))
    )
    assert isinstance(retry, RefreshRejected)
    fresh = await service.register_device_and_issue_session(
        registration(ctx, app_instance_id=device.app_instance_id,
                     now=NOW + timedelta(hours=2))
    )
    assert (await ctx.session.get(AccountSession, fresh.session_id)).security_version == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("account_id,now", [
    ("not-uuid", NOW),
    (None, datetime(2026, 7, 23, 13, 0)),
])
async def test_invalid_revoke_all_input_is_controlled_and_has_no_sql_changes(
    session_context, account_id, now,
):
    ctx = session_context
    issued = await make_service(ctx).register_device_and_issue_session(registration(ctx))
    version = ctx.account.security_version
    with pytest.raises(InvalidAccountSessionRequest):
        await make_service(ctx).revoke_all_account_sessions(
            RevokeAllAccountSessions(account_id or ctx.account.id, now)
        )
    await ctx.session.refresh(ctx.account)
    stored = await ctx.session.get(AccountSession, issued.session_id)
    assert ctx.account.security_version == version
    assert stored.status == "active" and stored.revoked_at is None
    assert (await ctx.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_late_error_rolls_back_savepoint_and_outer_transaction_survives(
    session_context, monkeypatch,
):
    ctx = session_context
    service = make_service(ctx)
    original = service._issue_first_session
    request = registration(ctx)
    account_id = request.account_id
    app_instance_id = request.app_instance_id

    async def late_failure(account, device, now):
        await original(account, device, now)
        raise RuntimeError("late session failure")

    monkeypatch.setattr(service, "_issue_first_session", late_failure)
    with pytest.raises(RuntimeError, match="late session failure"):
        await service.register_device_and_issue_session(request)
    assert (
        await ctx.session.execute(
            select(func.count()).select_from(AccountDevice).where(
                AccountDevice.account_id == account_id,
                AccountDevice.app_instance_id == app_instance_id,
            )
        )
    ).scalar_one() == 0
    assert (
        await ctx.session.execute(
            select(func.count()).select_from(AccountSession).where(
                AccountSession.account_id == account_id
            )
        )
    ).scalar_one() == 0
    assert (await ctx.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_unknown_integrity_error_is_not_masked(session_context, monkeypatch):
    ctx = session_context
    service = make_service(ctx)

    async def fail(*_):
        raise IntegrityError("insert", {}, RuntimeError("unknown constraint"))

    monkeypatch.setattr(service, "_issue_first_session", fail)
    with pytest.raises(IntegrityError):
        await service.register_device_and_issue_session(registration(ctx))


@pytest.mark.asyncio
async def test_concurrent_rotation_detects_reuse_and_compromises_family():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    account_id, device_id, session_id = uuid4(), uuid4(), uuid4()
    selector, family = uuid4(), uuid4()
    public_key = b"concurrent-key-" + account_id.bytes
    token = f"{selector}." + base64.urlsafe_b64encode(SECRET).rstrip(b"=").decode()
    async with AsyncSession(engine) as setup:
        account = Account(
            id=account_id, display_name="Concurrent", status="active",
            security_version=1,
        )
        device = AccountDevice(
            id=device_id, account_id=account_id, app_instance_id=uuid4(),
            platform="ios", display_name="Device", public_key=public_key,
            public_key_fingerprint=hashlib.sha256(public_key).digest(),
            quick_unlock_enabled=False, status="active", last_seen_at=NOW,
        )
        setup.add_all([account, device])
        await setup.flush()
        setup.add(AccountSession(
            id=session_id, account_id=account_id, device_id=device_id,
            token_selector=selector,
            refresh_secret_digest=hmac.new(
                PEPPER, selector.bytes + SECRET, hashlib.sha256
            ).digest(),
            refresh_family=family, previous_rotated_session_id=None,
            security_version=1, status="active", issued_at=NOW,
            last_used_at=None, idle_expires_at=NOW + timedelta(days=30),
            absolute_expires_at=NOW + timedelta(days=90),
            revoked_at=None, revoked_reason=None,
        ))
        await setup.commit()

    async def rotate():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                return await AccountSessionService(session, PEPPER).rotate_refresh_session(
                    RotateRefreshSession(token, NOW + timedelta(days=1))
                )

    results = await asyncio.gather(rotate(), rotate())
    assert sum(isinstance(item, RotatedRefreshSession) for item in results) == 1
    rejected = next(item for item in results if isinstance(item, RefreshRejected))
    assert rejected.reason == "refresh_token_reuse"
    async with AsyncSession(engine) as verify:
        active_count = (
            await verify.execute(
                select(func.count()).select_from(AccountSession).where(
                    AccountSession.refresh_family == family,
                    AccountSession.status == "active",
                )
            )
        ).scalar_one()
        compromised_count = (
            await verify.execute(
                select(func.count()).select_from(AccountSession).where(
                    AccountSession.refresh_family == family,
                    AccountSession.status == "compromised",
                )
            )
        ).scalar_one()
        assert active_count == 0 and compromised_count == 1
    await engine.dispose()
