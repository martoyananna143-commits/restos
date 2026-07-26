"""PostgreSQL integration tests for scoped browser logout."""

from datetime import datetime, timezone
import os
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routers import account_invitation_auth, account_web_sessions
from app.infra.database.models.account import Account, AccountDevice, AccountSession
from app.internal.services.account_session_service import (
    AccountSessionService,
    RegisterDeviceAndIssueSession,
)


NOW = datetime.now(timezone.utc)
ORIGIN = "https://restos.test"
HEADERS = {"Origin": ORIGIN, "X-RestOS-Web-Session": "1"}
PEPPER = b"p" * 32


class FailingCommitSession(AsyncSession):
    async def commit(self):
        raise RuntimeError("commit failed")


@pytest_asyncio.fixture
async def logout_context(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    account_id = uuid4()
    async with sessions() as setup:
        setup.add(
            Account(
                id=account_id,
                display_name="Logout account",
                status="active",
                security_version=1,
            )
        )
        await setup.commit()
        service = AccountSessionService(setup, PEPPER)
        current = await service.register_device_and_issue_session(
            RegisterDeviceAndIssueSession(
                account_id=account_id,
                app_instance_id=uuid4(),
                platform="web",
                display_name="Current browser",
                public_key=b"logout-current-" + uuid4().bytes,
                now=NOW,
            )
        )
        same_device = await service.register_device_and_issue_session(
            RegisterDeviceAndIssueSession(
                account_id=account_id,
                app_instance_id=(
                    await setup.get(AccountDevice, current.device_id)
                ).app_instance_id,
                platform="web",
                display_name="Current browser",
                public_key=(await setup.get(AccountDevice, current.device_id)).public_key,
                now=NOW,
            )
        )
        other_device = await service.register_device_and_issue_session(
            RegisterDeviceAndIssueSession(
                account_id=account_id,
                app_instance_id=uuid4(),
                platform="web",
                display_name="Other browser",
                public_key=b"logout-other-" + uuid4().bytes,
                now=NOW,
            )
        )
        await setup.commit()

    monkeypatch.setattr(
        account_web_sessions.config, "ACCOUNT_AUTH_SESSION_PEPPER", PEPPER.decode()
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

    def make_app(session_factory):
        async def session_override():
            async with session_factory() as session:
                yield session

        app = FastAPI()
        account_invitation_auth.configure_account_auth_http_security(app)
        app.include_router(account_web_sessions.router)
        app.dependency_overrides[
            account_invitation_auth.get_account_auth_session
        ] = session_override
        return app

    yield (
        engine,
        sessions,
        make_app,
        account_id,
        current,
        same_device,
        other_device,
    )
    await engine.dispose()


async def _logout(app, token):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/api/v1/auth/web/sessions/logout",
            headers=HEADERS,
            cookies={"restos_refresh": token} if token else None,
        )


@pytest.mark.asyncio
async def test_scoped_logout_revokes_only_current_session(logout_context):
    (
        _engine,
        sessions,
        make_app,
        account_id,
        current,
        same_device,
        other_device,
    ) = logout_context
    response = await _logout(make_app(sessions), current.refresh_token)
    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "Max-Age=0" in cookie and "Path=/api/v1/auth/web" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert response.headers["cache-control"] == "private, no-store"

    async with sessions() as verification:
        revoked = await verification.get(AccountSession, current.session_id)
        untouched_same = await verification.get(
            AccountSession, same_device.session_id
        )
        untouched_other = await verification.get(
            AccountSession, other_device.session_id
        )
        device = await verification.get(AccountDevice, current.device_id)
        account = await verification.get(Account, account_id)
        assert revoked.status == "revoked"
        assert revoked.revoked_at is not None
        assert revoked.revoked_reason == "web_logout"
        assert untouched_same.status == "active"
        assert untouched_other.status == "active"
        assert device.status == "active"
        assert device.quick_unlock_enabled is False
        assert account.security_version == 1

    repeated = await _logout(make_app(sessions), current.refresh_token)
    assert repeated.status_code == 204


@pytest.mark.asyncio
@pytest.mark.parametrize("token", [None, "malformed", f"{uuid4()}.{'x' * 43}"])
async def test_logout_unknown_cookie_is_idempotent_and_secret_safe(
    logout_context, token
):
    _engine, sessions, make_app, _account_id, current, *_rest = logout_context
    response = await _logout(make_app(sessions), token)
    assert response.status_code == 204
    assert not response.content
    assert token is None or token not in response.headers.get("set-cookie", "")
    async with sessions() as verification:
        assert (await verification.get(AccountSession, current.session_id)).status == "active"


@pytest.mark.asyncio
async def test_logout_commit_failure_rolls_back_and_sets_no_cookie(logout_context):
    engine, sessions, make_app, _account_id, current, *_rest = logout_context
    failing = async_sessionmaker(
        engine, class_=FailingCommitSession, expire_on_commit=False
    )
    response = await _logout(make_app(failing), current.refresh_token)
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_error"}}
    assert "set-cookie" not in response.headers
    async with sessions() as verification:
        assert (await verification.get(AccountSession, current.session_id)).status == "active"
        assert (await verification.execute(
            select(AccountSession.id).where(AccountSession.id == current.session_id)
        )).scalar_one() == current.session_id
