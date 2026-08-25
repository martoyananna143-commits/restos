"""HTTP boundary tests for browser-only Account sessions."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import account_auth
from app.api.routers import account_invitation_auth, account_web_sessions
from app.internal.services.account_access_token_service import (
    CurrentAccountPrincipal,
    IssuedAccountAccessToken,
)
from app.internal.services.account_session_service import RefreshRejected


NOW = datetime.now(timezone.utc)
ORIGIN = "https://restos.test"
HEADERS = {"Origin": ORIGIN, "X-RestOS-Web-Session": "1"}


class FakeSession:
    def __init__(self, *, commit_error=False):
        self.commits = 0
        self.rollbacks = 0
        self.commit_error = commit_error

    async def commit(self):
        self.commits += 1
        if self.commit_error:
            raise RuntimeError("commit failed")

    async def rollback(self):
        self.rollbacks += 1

    async def get(self, _model, _identifier):
        return SimpleNamespace(absolute_expires_at=NOW + timedelta(days=90))


def _rotated():
    return SimpleNamespace(
        account_id=uuid4(),
        device_id=uuid4(),
        session_id=uuid4(),
        previous_session_id=uuid4(),
        refresh_token=f"{uuid4()}.{'n' * 43}",
        refresh_family=uuid4(),
        idle_expires_at=NOW + timedelta(days=30),
        absolute_expires_at=NOW + timedelta(days=90),
    )


def _app(monkeypatch, session=None):
    session = session or FakeSession()
    monkeypatch.setattr(
        account_web_sessions.config, "ACCOUNT_AUTH_SESSION_PEPPER", "p" * 32
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
        yield session

    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(account_web_sessions.router)
    app.include_router(account_invitation_auth.router)
    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_override
    return TestClient(app), session, app


def test_web_refresh_rotates_cookie_and_returns_only_memory_token(monkeypatch):
    rotated = _rotated()

    class Sessions:
        def __init__(self, *_args):
            pass

        async def rotate_refresh_session(self, request):
            assert request.refresh_token == "old.refresh"
            return rotated

    class Tokens:
        async def issue(self, request):
            assert request.session_id == rotated.session_id
            return IssuedAccountAccessToken("access.jwt", NOW + timedelta(minutes=10))

    monkeypatch.setattr(account_web_sessions, "AccountSessionService", Sessions)
    monkeypatch.setattr(
        account_web_sessions, "account_access_token_service", lambda _session: Tokens()
    )
    http, session, _app_value = _app(monkeypatch)
    response = http.post(
        "/api/v1/auth/web/sessions/refresh",
        headers=HEADERS,
        cookies={"restos_refresh": "old.refresh"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "access_token": "access.jwt",
        "token_type": "bearer",
        "expires_at": (NOW + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    }
    assert "refresh" not in response.text
    cookie = response.headers["set-cookie"]
    assert rotated.refresh_token in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Path=/api/v1/auth/web" in cookie
    assert response.headers["cache-control"] == "private, no-store"
    assert session.commits == 1 and session.rollbacks == 0


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"X-RestOS-Web-Session": "1"}, 403),
        ({"Origin": ORIGIN}, 403),
        ({"Origin": ORIGIN, "X-RestOS-Web-Session": "0"}, 403),
        ({"Origin": "https://restos.test.evil.example", "X-RestOS-Web-Session": "1"}, 403),
        ({"Origin": "http://restos.test", "X-RestOS-Web-Session": "1"}, 403),
    ],
)
def test_web_csrf_boundary_is_exact(monkeypatch, headers, expected):
    http, _session, _app_value = _app(monkeypatch)
    response = http.post("/api/v1/auth/web/sessions/refresh", headers=headers)
    assert response.status_code == expected
    assert response.json()["detail"]["code"] == "permission_denied"
    assert response.headers["cache-control"] == "private, no-store"


def test_web_refresh_missing_cookie_is_safe(monkeypatch):
    http, _session, _app_value = _app(monkeypatch)
    response = http.post("/api/v1/auth/web/sessions/refresh", headers=HEADERS)
    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "invalid_or_expired_session"}
    }
    assert "restos_refresh" not in response.text


def test_web_refresh_rejection_clears_cookie(monkeypatch):
    class Sessions:
        def __init__(self, *_args):
            pass

        async def rotate_refresh_session(self, _request):
            return RefreshRejected("expired")

    monkeypatch.setattr(account_web_sessions, "AccountSessionService", Sessions)
    http, session, _app_value = _app(monkeypatch)
    response = http.post(
        "/api/v1/auth/web/sessions/refresh",
        headers=HEADERS,
        cookies={"restos_refresh": "old.refresh"},
    )
    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "invalid_or_expired_session"}
    }
    cookie = response.headers["set-cookie"]
    assert "restos_refresh=" in cookie
    assert "Max-Age=0" in cookie
    assert "Path=/api/v1/auth/web" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie
    assert response.headers["cache-control"] == "private, no-store"
    assert session.commits == 1


def test_web_refresh_commit_failure_never_sets_cookie(monkeypatch):
    rotated = _rotated()

    class Sessions:
        def __init__(self, *_args):
            pass

        async def rotate_refresh_session(self, _request):
            return rotated

    class Tokens:
        async def issue(self, _request):
            return IssuedAccountAccessToken("access.jwt", NOW + timedelta(minutes=10))

    monkeypatch.setattr(account_web_sessions, "AccountSessionService", Sessions)
    monkeypatch.setattr(
        account_web_sessions, "account_access_token_service", lambda _session: Tokens()
    )
    http, _session, _app_value = _app(monkeypatch, FakeSession(commit_error=True))
    response = http.post(
        "/api/v1/auth/web/sessions/refresh",
        headers=HEADERS,
        cookies={"restos_refresh": "old.refresh"},
    )
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_error"}}
    assert "set-cookie" not in response.headers


def test_logout_revokes_only_cookie_session_and_is_idempotent(monkeypatch):
    calls = []

    class Sessions:
        def __init__(self, *_args):
            pass

        async def revoke_current_refresh_session(self, request):
            calls.append(request.refresh_token)
            return SimpleNamespace(revoked=True)

    monkeypatch.setattr(account_web_sessions, "AccountSessionService", Sessions)
    http, session, _app_value = _app(monkeypatch)
    response = http.post(
        "/api/v1/auth/web/sessions/logout",
        headers=HEADERS,
        cookies={"restos_refresh": "current.refresh"},
    )
    assert response.status_code == 204 and response.content == b""
    assert calls == ["current.refresh"]
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert session.commits == 1

    response = http.post("/api/v1/auth/web/sessions/logout", headers=HEADERS)
    assert response.status_code == 204
    assert calls == ["current.refresh"]


def test_bootstrap_uses_bearer_principal_and_is_read_only(monkeypatch):
    account_id = uuid4()
    principal = CurrentAccountPrincipal(
        account_id=account_id,
        session_id=uuid4(),
        device_id=uuid4(),
        security_version=3,
        token_expires_at=NOW + timedelta(minutes=5),
    )
    company_id = uuid4()

    class Bootstrap:
        def __init__(self, _session):
            pass

        async def get(self, requested_account_id, _now):
            assert requested_account_id == account_id
            return SimpleNamespace(
                account_id=account_id,
                account_status="active",
                security_version=3,
                companies=(
                    SimpleNamespace(
                        company_id=company_id,
                        company_name="RestOS",
                        employee_profile_id=None,
                        relationship="owner",
                    ),
                ),
            )

    monkeypatch.setattr(account_web_sessions, "AccountBootstrapService", Bootstrap)
    http, session, app = _app(monkeypatch)
    app.dependency_overrides[account_auth.get_current_account_principal] = (
        lambda: principal
    )
    response = http.get("/api/v1/account/bootstrap")
    assert response.status_code == 200
    assert response.json()["account"]["id"] == str(account_id)
    assert response.json()["companies"][0]["company_id"] == str(company_id)
    assert session.commits == 0 and session.rollbacks == 0
    assert response.headers["cache-control"] == "private, no-store"


def test_openapi_has_no_refresh_secret_in_web_responses(monkeypatch):
    http, _session, _app_value = _app(monkeypatch)
    schema = http.get("/openapi.json").json()
    response_schema = schema["components"]["schemas"]["WebRefreshResponse"]
    assert "refresh_token" not in response_schema.get("properties", {})
    web_operation = schema["paths"]["/api/v1/auth/web/sessions/refresh"]["post"]
    assert "requestBody" not in web_operation


def test_web_registration_wraps_native_contract_without_exposing_refresh(monkeypatch):
    native = account_invitation_auth.RegistrationResponse(
        account_id=uuid4(),
        employee_profile_id=uuid4(),
        employee_assignment_id=uuid4(),
        company_id=uuid4(),
        device_id=uuid4(),
        session_id=uuid4(),
        access_token="access.jwt",
        access_token_expires_at=NOW + timedelta(minutes=10),
        refresh_token=f"{uuid4()}.{'r' * 43}",
        display_name="Employee",
        company_name="Synthetic Company",
        position_name="Synthetic Position",
        venue_names=("Synthetic Venue",),
    )

    async def fake_register(_body, _response, _session):
        return native

    monkeypatch.setattr(account_invitation_auth, "register", fake_register)
    http, _session, _app_value = _app(monkeypatch)
    payload = {
        "invitation_code": "123456",
        "phone_verification_challenge_id": str(uuid4()),
        "phone": "+79990000000",
        "display_name": "Employee",
        "password": "strong-password",
        "app_instance_id": str(uuid4()),
        "platform": "web",
        "device_challenge_id": str(uuid4()),
        "device_challenge_nonce": "n" * 43,
        "device_challenge_signature": "signature",
        "document_set_version": "restos-account-legal-2026-08-10-v1",
        "terms_version": "restos-terms-2026-08-10-v1",
        "privacy_version": "restos-privacy-2026-08-10-v1",
    }
    response = http.post(
        "/api/v1/auth/invitations/register/web",
        headers=HEADERS,
        json=payload,
    )
    assert response.status_code == 200
    assert "refresh_token" not in response.json()
    assert native.refresh_token in response.headers["set-cookie"]
    assert response.json()["access_token"] == "access.jwt"
