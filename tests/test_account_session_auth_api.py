"""HTTP tests for Account bearer authentication and refresh."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import account_auth
from app.api.routers import account_invitation_auth, account_sessions
from app.internal.services.account_access_token_service import (
    AccountAccessTokenConfigurationError,
    AccountAccessTokenRejected,
    CurrentAccountPrincipal,
    IssuedAccountAccessToken,
)
from app.internal.services.account_session_service import (
    InvalidRefreshSession,
    RefreshRejected,
)


NOW = datetime.now(timezone.utc)


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def app_client(monkeypatch, session=None):
    session = session or FakeSession()
    monkeypatch.setattr(
        account_sessions.config, "ACCOUNT_AUTH_SESSION_PEPPER", "s" * 32
    )

    async def session_override():
        yield session

    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(account_sessions.router)

    @app.get("/protected")
    async def protected(
        principal: CurrentAccountPrincipal = Depends(
            account_auth.get_current_account_principal
        ),
    ):
        return {"account_id": str(principal.account_id)}

    @app.get("/legacy/{item_id}")
    async def legacy(item_id: int):
        return {"item_id": item_id}

    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_override
    return TestClient(app), session


def rotated():
    return SimpleNamespace(
        account_id=uuid4(),
        device_id=uuid4(),
        session_id=uuid4(),
        previous_session_id=uuid4(),
        refresh_token=f"{uuid4()}.new-secret",
        refresh_family=uuid4(),
        idle_expires_at=NOW + timedelta(days=30),
        absolute_expires_at=NOW + timedelta(days=90),
    )


def test_refresh_rotates_and_returns_access_token(monkeypatch):
    result = rotated()

    class Sessions:
        def __init__(self, *_args, **_kwargs):
            pass

        async def rotate_refresh_session(self, request):
            assert request.refresh_token == "old.refresh-secret"
            return result

    class Tokens:
        async def issue(self, request):
            assert request.session_id == result.session_id
            return IssuedAccountAccessToken(
                "access.jwt.value", NOW + timedelta(minutes=10)
            )

    monkeypatch.setattr(account_sessions, "AccountSessionService", Sessions)
    monkeypatch.setattr(
        account_sessions, "account_access_token_service", lambda _session: Tokens()
    )
    http, session = app_client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/sessions/refresh",
            json={"refresh_token": "old.refresh-secret"},
        )
    assert response.status_code == 200
    assert response.json() == {
        "access_token": "access.jwt.value",
        "access_token_expires_at": (NOW + timedelta(minutes=10)).isoformat().replace(
            "+00:00", "Z"
        ),
        "refresh_token": result.refresh_token,
        "refresh_session_id": str(result.session_id),
        "refresh_idle_expires_at": result.idle_expires_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "refresh_absolute_expires_at": result.absolute_expires_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "token_type": "bearer",
    }
    assert session.commits == 1 and session.rollbacks == 0
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("result", [RefreshRejected("rotated"), InvalidRefreshSession("bad")])
def test_refresh_rejection_is_safe(monkeypatch, result):
    class Sessions:
        def __init__(self, *_args, **_kwargs):
            pass

        async def rotate_refresh_session(self, _request):
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(account_sessions, "AccountSessionService", Sessions)
    http, session = app_client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/sessions/refresh",
            json={"refresh_token": "secret-value"},
        )
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "authentication_required"}}
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["cache-control"] == "no-store"
    assert "secret-value" not in response.text
    if isinstance(result, RefreshRejected):
        assert session.commits == 1
    else:
        assert session.rollbacks == 1


def test_refresh_configuration_unavailable_is_503(monkeypatch):
    monkeypatch.setattr(account_sessions.config, "ACCOUNT_AUTH_SESSION_PEPPER", "")
    http, session = app_client(monkeypatch)
    monkeypatch.setattr(account_sessions.config, "ACCOUNT_AUTH_SESSION_PEPPER", "")
    with http:
        response = http.post(
            "/api/v1/auth/sessions/refresh",
            json={"refresh_token": "secret-value"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "configuration_unavailable"}}
    assert response.headers["cache-control"] == "no-store"
    assert session.rollbacks == 0


def test_protected_dependency_accepts_principal(monkeypatch):
    expected = CurrentAccountPrincipal(
        uuid4(), uuid4(), uuid4(), 1, NOW + timedelta(minutes=10)
    )

    class Tokens:
        async def verify(self, request):
            assert request.access_token == "valid-token"
            return expected

    monkeypatch.setattr(
        account_auth, "account_access_token_service", lambda _session: Tokens()
    )
    http, _ = app_client(monkeypatch)
    with http:
        response = http.get(
            "/protected", headers={"Authorization": "Bearer valid-token"}
        )
    assert response.status_code == 200
    assert response.json() == {"account_id": str(expected.account_id)}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer invalid"}],
)
def test_protected_dependency_rejects_missing_or_invalid(monkeypatch, headers):
    class Tokens:
        async def verify(self, _request):
            raise AccountAccessTokenRejected("internal reason")

    monkeypatch.setattr(
        account_auth, "account_access_token_service", lambda _session: Tokens()
    )
    http, _ = app_client(monkeypatch)
    with http:
        response = http.get("/protected", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "authentication_required"}}
    assert response.headers["www-authenticate"] == "Bearer"
    assert "internal reason" not in response.text


def test_refresh_validation_and_unexpected_500_are_no_store(monkeypatch):
    class BrokenSessions:
        def __init__(self, *_args, **_kwargs):
            pass

        async def rotate_refresh_session(self, _request):
            raise RuntimeError("private database details")

    monkeypatch.setattr(account_sessions, "AccountSessionService", BrokenSessions)
    http, _ = app_client(monkeypatch)
    with http:
        invalid = http.post("/api/v1/auth/sessions/refresh", json={})
        broken = http.post(
            "/api/v1/auth/sessions/refresh",
            json={"refresh_token": "secret-value"},
        )
        legacy = http.get("/legacy/not-an-int")
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": {"code": "invalid_request"}}
    assert invalid.headers["cache-control"] == "no-store"
    assert broken.status_code == 500
    assert broken.json() == {"detail": {"code": "internal_error"}}
    assert "private database details" not in broken.text
    assert broken.headers["cache-control"] == "no-store"
    assert legacy.status_code == 422
    assert isinstance(legacy.json()["detail"], list)
    assert "cache-control" not in legacy.headers


def test_openapi_has_no_secret_examples(monkeypatch):
    http, _ = app_client(monkeypatch)
    schema = str(http.app.openapi()).lower()
    assert "secret-value" not in schema
    assert "account_auth_access_token_key" not in schema
    assert "session_pepper" not in schema
