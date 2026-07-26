"""HTTP integration coverage for the Account bootstrap bearer boundary."""

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
from jose import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routers import account_invitation_auth, account_web_sessions
from app.infra.database.models.access_profile import AccessProfile
from app.infra.database.models.account import Account, AccountDevice, AccountSession
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.internal.services.account_access_token_service import (
    AccountAccessTokenService,
    IssueAccountAccessToken,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    RegisterDeviceAndIssueSession,
)


NOW = datetime.now(timezone.utc)
ACCESS_KEY = b"k" * 32
SESSION_PEPPER = b"p" * 32


async def _company(session, owner, name="Company"):
    identifier = uuid4()
    company = Company(
        id=identifier,
        owner_account_id=owner.id,
        name=name,
        code=f"bootstrap-http-{identifier.hex}",
        timezone="Europe/Moscow",
        locale="ru-RU",
        status="active",
    )
    session.add(company)
    await session.flush()
    return company


async def _employee_company(session, account, name="Employee Company"):
    owner = Account(
        id=uuid4(),
        display_name="Other owner",
        status="active",
        security_version=1,
    )
    session.add(owner)
    await session.flush()
    company = await _company(session, owner, name)
    profile = EmployeeProfile(
        id=uuid4(),
        company_id=company.id,
        account_id=account.id,
        full_name="Bootstrap employee",
        employment_status="active",
        hired_at=NOW,
    )
    session.add(profile)
    await session.flush()
    marker = uuid4().hex
    access = AccessProfile(
        id=uuid4(),
        company_id=company.id,
        name="Bootstrap HTTP access",
        code=f"bootstrap-http-access-{marker}",
        maximum_scope="company",
        is_active=True,
    )
    session.add(access)
    await session.flush()
    position = Position(
        id=uuid4(),
        company_id=company.id,
        name="Bootstrap HTTP position",
        code=f"bootstrap-http-position-{marker}",
        is_active=True,
    )
    session.add(position)
    await session.flush()
    assignment = EmployeeAssignment(
        id=uuid4(),
        company_id=company.id,
        employee_profile_id=profile.id,
        position_id=position.id,
        access_profile_id=access.id,
        scope_type="company",
        is_primary=True,
        status="active",
        starts_at=NOW - timedelta(days=1),
    )
    session.add(assignment)
    await session.flush()
    return SimpleNamespace(company=company, profile=profile)


def _app(session_dependency):
    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(account_web_sessions.router)
    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_dependency
    return app


@pytest_asyncio.fixture
async def bootstrap_http_context(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        transaction = await session.begin()
        account = Account(
            id=uuid4(),
            display_name="Bootstrap Account",
            status="active",
            security_version=3,
        )
        session.add(account)
        await session.flush()
        issued_session = await AccountSessionService(
            session, SESSION_PEPPER
        ).register_device_and_issue_session(
            RegisterDeviceAndIssueSession(
                account_id=account.id,
                app_instance_id=uuid4(),
                platform="web",
                display_name="Bootstrap browser",
                public_key=b"bootstrap-http-key-" + uuid4().bytes,
                now=NOW,
            )
        )
        access = await AccountAccessTokenService(
            session, ACCESS_KEY
        ).issue(
            IssueAccountAccessToken(
                account_id=account.id,
                session_id=issued_session.session_id,
                device_id=issued_session.device_id,
                now=NOW,
            )
        )
        monkeypatch.setattr(
            account_web_sessions.config,
            "ACCOUNT_AUTH_ACCESS_TOKEN_KEY",
            ACCESS_KEY.decode(),
        )
        monkeypatch.setattr(
            account_web_sessions.config,
            "ACCOUNT_AUTH_ACCESS_TOKEN_TTL_SECONDS",
            600,
        )

        async def session_dependency():
            yield session

        app = _app(session_dependency)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield SimpleNamespace(
                client=client,
                app=app,
                session=session,
                account=account,
                session_id=issued_session.session_id,
                device_id=issued_session.device_id,
                access_token=access.access_token,
            )
        await transaction.rollback()
    await engine.dispose()


async def _get(context, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return await context.client.get(
        "/api/v1/account/bootstrap", headers=headers, **kwargs
    )


def _claims(context, **changes):
    issued = int(NOW.timestamp())
    claims = {
        "sub": str(context.account.id),
        "sid": str(context.session_id),
        "did": str(context.device_id),
        "sv": context.account.security_version,
        "iat": issued,
        "nbf": issued,
        "exp": issued + 300,
        "iss": "restos-account-auth",
        "aud": "restos-api",
        "typ": "access",
    }
    claims.update(changes)
    return claims


def _token(context, key=ACCESS_KEY, **changes):
    return jwt.encode(_claims(context, **changes), key, algorithm="HS256")


def _assert_safe(response, status_code=401, code="authentication_required"):
    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": code}}
    assert response.headers["cache-control"] == "private, no-store"
    forbidden = (
        "refresh_token",
        "selector",
        "digest",
        "hmac",
        "traceback",
        "sql",
    )
    assert not any(value in response.text.lower() for value in forbidden)


@pytest.mark.asyncio
async def test_positive_owner_bootstrap(bootstrap_http_context):
    context = bootstrap_http_context
    company = await _company(context.session, context.account, "Owner Company")
    response = await _get(context, context.access_token)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "account": {
            "id": str(context.account.id),
            "status": "active",
            "security_version": 3,
        },
        "companies": [
            {
                "company_id": str(company.id),
                "company_name": "Owner Company",
                "employee_profile_id": None,
                "relationship": "owner",
            }
        ],
    }
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_positive_employee_bootstrap(bootstrap_http_context):
    context = bootstrap_http_context
    graph = await _employee_company(context.session, context.account)
    response = await _get(context, context.access_token)
    assert response.status_code == 200
    company = response.json()["companies"][0]
    assert company["company_id"] == str(graph.company.id)
    assert company["employee_profile_id"] == str(graph.profile.id)
    assert company["relationship"] == "employee"


@pytest.mark.asyncio
async def test_empty_membership(bootstrap_http_context):
    response = await _get(
        bootstrap_http_context, bootstrap_http_context.access_token
    )
    assert response.status_code == 200
    assert response.json()["companies"] == []


@pytest.mark.asyncio
async def test_multiple_companies_have_deterministic_json_order(
    bootstrap_http_context,
):
    context = bootstrap_http_context
    first = await _company(context.session, context.account, " zeta ")
    second = await _company(context.session, context.account, "Alpha")
    response = await _get(context, context.access_token)
    assert [entry["company_id"] for entry in response.json()["companies"]] == [
        str(second.id),
        str(first.id),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("authorization", "token_factory"),
    [
        (None, None),
        ("Basic abc", None),
        ("Bearer malformed", None),
        (None, lambda context: _token(context, key=b"x" * 32)),
        (None, lambda context: _token(context, iss="wrong")),
        (None, lambda context: _token(context, aud="wrong")),
        (None, lambda context: _token(context, typ="refresh")),
        (None, lambda context: _token(context, exp=int(NOW.timestamp()) - 1)),
        (None, lambda context: _token(context, sub=str(uuid4()))),
    ],
)
async def test_invalid_bearer_is_safely_rejected(
    bootstrap_http_context, authorization, token_factory
):
    context = bootstrap_http_context
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    elif token_factory is not None:
        headers["Authorization"] = f"Bearer {token_factory(context)}"
    response = await context.client.get(
        "/api/v1/account/bootstrap", headers=headers
    )
    _assert_safe(response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "account_suspended",
        "account_disabled",
        "account_deleted",
        "session_revoked",
        "session_expired",
        "session_compromised",
        "device_revoked",
        "security_version",
    ],
)
async def test_database_auth_state_is_safely_rejected(
    bootstrap_http_context, change
):
    context = bootstrap_http_context
    account_session = await context.session.get(
        AccountSession, context.session_id
    )
    device = await context.session.get(AccountDevice, context.device_id)
    if change == "account_suspended":
        context.account.status = "suspended"
    elif change == "account_disabled":
        context.account.status = "disabled"
    elif change == "account_deleted":
        context.account.deleted_at = NOW
    elif change in {"session_revoked", "session_compromised"}:
        account_session.status = change.removeprefix("session_")
        account_session.revoked_at = NOW
        account_session.revoked_reason = "test"
    elif change == "session_expired":
        past = NOW - timedelta(seconds=1)
        account_session.issued_at = NOW - timedelta(days=1)
        account_session.idle_expires_at = past
        account_session.absolute_expires_at = past
    elif change == "device_revoked":
        device.status = "revoked"
        device.revoked_at = NOW
        device.revoked_reason = "test"
    else:
        context.account.security_version += 1
    await context.session.flush()
    response = await _get(context, context.access_token)
    _assert_safe(response)
    assert (await context.session.execute(select(1))).scalar_one() == 1


@pytest.mark.asyncio
async def test_identity_spoofing_inputs_are_not_trusted(bootstrap_http_context):
    context = bootstrap_http_context
    response = await _get(
        context,
        context.access_token,
        params={"account_id": str(uuid4()), "org_id": "123"},
        headers={"X-Account-Id": str(uuid4()), "X-Organization-Id": "123"},
    )
    assert response.status_code == 200
    assert response.json()["account"]["id"] == str(context.account.id)
    assert response.json()["companies"] == []


@pytest.mark.asyncio
async def test_bearer_cannot_see_other_accounts_company(bootstrap_http_context):
    context = bootstrap_http_context
    other = Account(
        id=uuid4(),
        display_name="Other owner",
        status="active",
        security_version=1,
    )
    context.session.add(other)
    await context.session.flush()
    await _company(context.session, other)
    response = await _get(context, context.access_token)
    assert response.status_code == 200
    assert response.json()["companies"] == []


@pytest.mark.asyncio
async def test_legacy_jwt_is_not_account_access_token(bootstrap_http_context):
    legacy = jwt.encode(
        {
            "sub": "legacy-user",
            "org_id": 123,
            "exp": int(NOW.timestamp()) + 300,
        },
        ACCESS_KEY,
        algorithm="HS256",
    )
    response = await _get(bootstrap_http_context, legacy)
    _assert_safe(response)


@pytest.mark.asyncio
async def test_configuration_unavailable_is_safe(bootstrap_http_context, monkeypatch):
    monkeypatch.setattr(
        account_web_sessions.config, "ACCOUNT_AUTH_ACCESS_TOKEN_KEY", ""
    )
    response = await _get(
        bootstrap_http_context, bootstrap_http_context.access_token
    )
    _assert_safe(response, 503, "configuration_unavailable")


@pytest.mark.asyncio
async def test_unexpected_bootstrap_failure_is_safe(
    bootstrap_http_context, monkeypatch
):
    class BrokenBootstrap:
        def __init__(self, _session):
            pass

        async def get(self, *_args):
            raise RuntimeError("sensitive database failure")

    monkeypatch.setattr(
        account_web_sessions, "AccountBootstrapService", BrokenBootstrap
    )
    response = await _get(
        bootstrap_http_context, bootstrap_http_context.access_token
    )
    _assert_safe(response, 500, "internal_error")
    assert "sensitive" not in response.text


@pytest.mark.asyncio
async def test_success_is_read_only(bootstrap_http_context):
    context = bootstrap_http_context

    class ReadOnlyProxy:
        def __init__(self, delegate):
            self.delegate = delegate

        async def get(self, *args, **kwargs):
            return await self.delegate.get(*args, **kwargs)

        async def execute(self, *args, **kwargs):
            return await self.delegate.execute(*args, **kwargs)

        def __getattr__(self, name):
            if name in {
                "add",
                "add_all",
                "flush",
                "commit",
                "rollback",
                "begin",
                "begin_nested",
            }:
                raise AssertionError(f"{name} must not be used")
            return getattr(self.delegate, name)

    proxy = ReadOnlyProxy(context.session)

    async def dependency():
        yield proxy

    context.app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = dependency
    response = await _get(context, context.access_token)
    assert response.status_code == 200
    assert (await context.session.execute(text("SELECT 1"))).scalar_one() == 1


def test_bootstrap_openapi_contract(monkeypatch):
    monkeypatch.setattr(
        account_web_sessions.config,
        "ACCOUNT_AUTH_ACCESS_TOKEN_KEY",
        ACCESS_KEY.decode(),
    )

    async def unused_session():
        raise AssertionError("OpenAPI must not use SQL")
        yield

    app = _app(unused_session)
    schema = app.openapi()
    path = "/api/v1/account/bootstrap"
    assert list(key for key in schema["paths"] if key == path) == [path]
    operation = schema["paths"][path]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert not operation.get("parameters")
    serialized = str(operation).lower()
    for forbidden in (
        "refresh_token",
        "cookie",
        "selector",
        "digest",
        "legacy",
        "org_id",
    ):
        assert forbidden not in serialized
