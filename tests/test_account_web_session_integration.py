"""PostgreSQL HTTP integration tests for browser refresh rotation."""

from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routers import account_invitation_auth, account_web_sessions
from app.infra.database.models.account import Account, AccountDevice, AccountSession
from app.internal.services.account_access_token_service import (
    AccountAccessTokenService,
    VerifyAccountAccessToken,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    RegisterDeviceAndIssueSession,
)


NOW = datetime.now(timezone.utc)
ORIGIN = "https://restos.test:8443"
HEADERS = {"Origin": ORIGIN, "X-RestOS-Web-Session": "1"}
PEPPER = b"p" * 32
ACCESS_KEY = b"k" * 32


@pytest_asyncio.fixture
async def web_refresh_context(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    account_id = uuid4()
    device_key_id = uuid4()
    async with sessions() as setup:
        account = Account(
            id=account_id,
            display_name="Web account",
            status="active",
            security_version=1,
        )
        setup.add(account)
        await setup.commit()
        issued = await AccountSessionService(setup, PEPPER).register_device_and_issue_session(
            RegisterDeviceAndIssueSession(
                account_id=account_id,
                app_instance_id=uuid4(),
                platform="web",
                display_name="Browser",
                public_key=b"test-public-key-" + device_key_id.bytes,
                now=NOW,
            )
        )
        await setup.commit()

    monkeypatch.setattr(
        account_web_sessions.config, "ACCOUNT_AUTH_SESSION_PEPPER", PEPPER.decode()
    )
    monkeypatch.setattr(
        account_web_sessions.config,
        "ACCOUNT_AUTH_ACCESS_TOKEN_KEY",
        ACCESS_KEY.decode(),
    )
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_ALLOWED_ORIGINS", [ORIGIN]
    )
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_REFRESH_COOKIE_NAME",
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
    app.include_router(account_web_sessions.router)
    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        yield client, sessions, issued, account_id
    await engine.dispose()


async def _refresh(client, token):
    return await client.post(
        "/api/v1/auth/web/sessions/refresh",
        headers=HEADERS,
        cookies={"restos_refresh": token},
    )


@pytest.mark.asyncio
async def test_real_web_rotation_access_and_reuse_compromise(web_refresh_context):
    client, sessions, issued, account_id = web_refresh_context
    first = await _refresh(client, issued.refresh_token)
    assert first.status_code == 200
    assert "refresh_token" not in first.json()
    cookie = first.cookies.get("restos_refresh")
    assert cookie and cookie != issued.refresh_token
    assert "HttpOnly" in first.headers["set-cookie"]
    assert "Path=/api/v1/auth/web" in first.headers["set-cookie"]

    async with sessions() as verification:
        principal = await AccountAccessTokenService(
            verification, ACCESS_KEY
        ).verify(
            VerifyAccountAccessToken(
                access_token=first.json()["access_token"],
                now=datetime.now(timezone.utc),
            )
        )
        assert principal.account_id == account_id

    reused = await _refresh(client, issued.refresh_token)
    assert reused.status_code == 401
    assert reused.json() == {
        "detail": {"code": "invalid_or_expired_session"}
    }
    async with sessions() as verification:
        successor = (
            await verification.execute(
                select(AccountSession).where(
                    AccountSession.previous_rotated_session_id == issued.session_id
                )
            )
        ).scalar_one()
        assert successor.status == "compromised"
        assert successor.revoked_reason == "refresh_token_reuse"
        assert (
            await verification.execute(
                select(Account.id).where(Account.id == account_id)
            )
        ).scalar_one() == account_id


@pytest.mark.asyncio
async def test_wrong_secret_does_not_compromise_family(web_refresh_context):
    client, sessions, issued, _account_id = web_refresh_context
    selector = issued.refresh_token.split(".", 1)[0]
    response = await _refresh(client, f"{selector}.{'x' * 43}")
    assert response.status_code == 401
    async with sessions() as verification:
        current = await verification.get(AccountSession, issued.session_id)
        assert current.status == "active"
        assert current.revoked_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "revoked",
        "compromised",
        "idle_expired",
        "absolute_expired",
        "account_suspended",
        "account_disabled",
        "account_deleted",
        "device_revoked",
        "security_version",
    ],
)
async def test_real_web_refresh_rejects_database_state(
    web_refresh_context, change
):
    client, sessions, issued, account_id = web_refresh_context
    async with sessions() as mutation:
        current = await mutation.get(AccountSession, issued.session_id)
        account = await mutation.get(Account, account_id)
        device = await mutation.get(AccountDevice, issued.device_id)
        if change in {"revoked", "compromised"}:
            current.status = change
            current.revoked_at = NOW
            current.revoked_reason = "test"
        elif change == "idle_expired":
            current.issued_at = NOW - timedelta(days=1)
            current.idle_expires_at = NOW - timedelta(seconds=1)
        elif change == "absolute_expired":
            past = NOW - timedelta(seconds=1)
            current.issued_at = NOW - timedelta(days=1)
            current.idle_expires_at = past
            current.absolute_expires_at = past
        elif change == "account_suspended":
            account.status = "suspended"
        elif change == "account_disabled":
            account.status = "disabled"
        elif change == "account_deleted":
            account.deleted_at = NOW
        elif change == "device_revoked":
            device.status = "revoked"
            device.revoked_at = NOW
            device.revoked_reason = "test"
        else:
            account.security_version += 1
        await mutation.commit()

    response = await _refresh(client, issued.refresh_token)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_or_expired_session"
    assert "Max-Age=0" in response.headers["set-cookie"]
