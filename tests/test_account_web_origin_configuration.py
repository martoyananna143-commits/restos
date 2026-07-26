"""Origin, CSRF, and configuration tests for the Account web boundary."""

import os
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.routers import account_invitation_auth, account_web_sessions


class FakeSession:
    async def commit(self):
        pass

    async def rollback(self):
        pass


def _client(monkeypatch, origins):
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_ALLOWED_ORIGINS", origins
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
        yield FakeSession()

    app = FastAPI()
    account_invitation_auth.configure_account_auth_http_security(app)
    app.include_router(account_web_sessions.router)

    @app.get("/legacy/{item_id}")
    async def legacy(item_id: int):
        return {"item_id": item_id}

    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_override
    return TestClient(app)


@pytest.mark.parametrize(
    ("configured", "presented"),
    [
        ("https://restos.test", "https://restos.test"),
        ("https://restos.test", "https://restos.test:443"),
        ("http://restos.test", "http://restos.test:80"),
        ("https://restos.test:8443", "https://restos.test:8443"),
    ],
)
def test_exact_normalized_origin_passes_csrf_boundary(
    monkeypatch, configured, presented
):
    response = _client(monkeypatch, [configured]).post(
        "/api/v1/auth/web/sessions/refresh",
        headers={"Origin": presented, "X-RestOS-Web-Session": "1"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_or_expired_session"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "origin",
    [
        "https://restos.test:8444",
        "http://restos.test:8443",
        "https://other.test:8443",
        "https://restos.test.evil.example",
        "https://evil-restos.test:8443",
        "https://user:password@restos.test:8443",
        "https://restos.test:8443/path",
        "https://restos.test:8443?query=value",
        "https://restos.test:8443#fragment",
    ],
)
def test_non_exact_or_malformed_presented_origin_is_denied(monkeypatch, origin):
    response = _client(monkeypatch, ["https://restos.test:8443"]).post(
        "/api/v1/auth/web/sessions/refresh",
        headers={"Origin": origin, "X-RestOS-Web-Session": "1"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "permission_denied"}}
    assert origin not in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "headers",
    [
        {"X-RestOS-Web-Session": "1"},
        {"Origin": "https://restos.test:8443"},
        {"Origin": "https://restos.test:8443", "X-RestOS-Web-Session": "wrong"},
    ],
)
def test_origin_and_exact_custom_header_are_both_required(monkeypatch, headers):
    response = _client(monkeypatch, ["https://restos.test:8443"]).post(
        "/api/v1/auth/web/sessions/refresh", headers=headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


@pytest.mark.parametrize(
    "origins",
    [
        [],
        ["*"],
        ["https://restos.test/path"],
        ["https://user@restos.test"],
        ["not-an-origin"],
    ],
)
def test_invalid_allowed_origin_configuration_is_safe_503(monkeypatch, origins):
    response = _client(monkeypatch, origins).post(
        "/api/v1/auth/web/sessions/refresh",
        headers={
            "Origin": "https://restos.test",
            "X-RestOS-Web-Session": "1",
        },
    )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "configuration_unavailable"}}
    assert "restos.test" not in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("ACCOUNT_WEB_REFRESH_COOKIE_NAME", "invalid cookie"),
        ("ACCOUNT_WEB_REFRESH_COOKIE_SAMESITE", "invalid"),
        ("ACCOUNT_WEB_REFRESH_COOKIE_SAMESITE", "none"),
    ],
)
def test_incomplete_cookie_configuration_is_safe_503(
    monkeypatch, attribute, value
):
    http = _client(monkeypatch, ["https://restos.test"])
    monkeypatch.setattr(account_invitation_auth.config, attribute, value)
    response = http.post(
        "/api/v1/auth/web/sessions/refresh",
        headers={"Origin": "https://restos.test", "X-RestOS-Web-Session": "1"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "configuration_unavailable"}}
    assert response.headers["cache-control"] == "private, no-store"


def test_production_rejects_insecure_web_cookie_at_request_not_startup(monkeypatch):
    http = _client(monkeypatch, ["https://restos.test"])
    monkeypatch.setattr(account_invitation_auth.config, "APP_ENV", "production")
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_REFRESH_COOKIE_SECURE", False
    )
    response = http.post(
        "/api/v1/auth/web/sessions/refresh",
        headers={"Origin": "https://restos.test", "X-RestOS-Web-Session": "1"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "configuration_unavailable"


def test_production_app_starts_without_active_web_session(monkeypatch):
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "production",
            "JWT_SECRET_KEY": "j" * 64,
            "WEBAPP_SECRET_KEY": "w" * 64,
            "DEFAULT_ADMIN_PASSWORD": "Strong-Test-Password-20",
            "INTERNAL_API_KEY": "i" * 64,
            "CORS_ORIGINS": "https://restos.test",
            "CORS_ALLOW_CREDENTIALS": "true",
            "ACCOUNT_WEB_ALLOWED_ORIGINS": "",
        }
    )
    result = subprocess.run(
        [
            "python",
            "-c",
            (
                "from app.api.main import create_app;"
                "app=create_app();"
                "paths={route.path for route in app.routes};"
                "assert '/health' in paths;"
                "assert '/api/v1/auth/web/sessions/refresh' in paths;"
                "assert '/api/v1/auth/web/sessions/logout' in paths;"
                "assert '/api/v1/account/bootstrap' in paths"
            ),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_legacy_validation_shape_is_unchanged(monkeypatch):
    response = _client(monkeypatch, ["https://restos.test"]).get(
        "/legacy/not-an-int"
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert response.headers.get("cache-control") != "private, no-store"
