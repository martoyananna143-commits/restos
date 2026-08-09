"""Strict HTTP declaration and security tests for standalone Account auth."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.routers import account_invitation_auth as invitation_auth
from app.api.routers import account_standalone_auth as auth
from app.internal.services.account_access_token_service import IssuedAccountAccessToken
from app.internal.services.phone_verification_service import (
    PhoneVerificationCodeRequested,
    SmsDeliveryFailed,
)
from app.internal.services.standalone_account_auth_service import (
    AuthenticatedStandaloneAccount,
    ResetStandaloneAccountPasswordResult,
    StandaloneAccountAuthUnavailable,
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


def client(monkeypatch, session=None):
    session = session or FakeSession()
    for name, value in (
        ("ACCOUNT_AUTH_INVITATION_PEPPER", "i" * 32),
        ("ACCOUNT_AUTH_PHONE_PEPPER", "p" * 32),
        ("ACCOUNT_AUTH_CODE_PEPPER", "c" * 32),
        ("ACCOUNT_AUTH_SESSION_PEPPER", "s" * 32),
        ("ACCOUNT_AUTH_ACCESS_TOKEN_KEY", "a" * 32),
        ("ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN", "pilot.restos.space"),
        ("ACCOUNT_WEB_ALLOWED_ORIGINS", ["https://testserver"]),
        ("ACCOUNT_WEB_REFRESH_COOKIE_SECURE", True),
        ("ACCOUNT_WEB_REFRESH_COOKIE_SAMESITE", "lax"),
        ("SMS_PROVIDER", "disabled"),
    ):
        monkeypatch.setattr(auth.config, name, value)
        if hasattr(invitation_auth.config, name):
            monkeypatch.setattr(invitation_auth.config, name, value)

    async def session_override():
        yield session

    app = FastAPI()
    invitation_auth.configure_account_auth_http_security(app)
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_account_auth_session] = session_override
    return TestClient(app), session


def headers():
    return {
        "Origin": "https://testserver",
        "X-RestOS-Web-Session": "1",
    }


def auth_result():
    return AuthenticatedStandaloneAccount(
        account_id=uuid4(),
        device_id=uuid4(),
        session_id=uuid4(),
        refresh_token="selector.synthetic-refresh-secret",
        absolute_expires_at=NOW + timedelta(days=30),
        display_name="Pilot Account",
    )


def test_openapi_has_typed_standalone_operations_and_forbids_unknown_fields(monkeypatch):
    http, _ = client(monkeypatch)
    schema = http.app.openapi()
    paths = {
        path: operation
        for path, operation in schema["paths"].items()
        if path.startswith("/api/v1/auth/account/")
    }
    assert len(paths) == 8
    for operation in paths.values():
        post = operation["post"]
        assert "responses" in post
        assert post["responses"].get("200") or post["responses"].get("202")
    request_models = [
        schema["components"]["schemas"][name]
        for name in (
            "RegistrationSmsRequest",
            "SmsVerifyRequest",
            "AccountDeviceChallengeRequest",
            "StandaloneRegistrationRequest",
            "PasswordLoginRequest",
            "PasswordResetRequest",
            "PasswordResetCompleteRequest",
        )
    ]
    assert all(model.get("additionalProperties") is False for model in request_models)
    assert "refresh_token" not in str(schema)


def test_csrf_origin_and_header_are_required(monkeypatch):
    http, _ = client(monkeypatch)
    with http:
        missing = http.post(
            "/api/v1/auth/account/registration/sms/request",
            json={"phone": "+79991234567"},
        )
        wrong = http.post(
            "/api/v1/auth/account/registration/sms/request",
            json={"phone": "+79991234567"},
            headers={
                "Origin": "https://evil.example",
                "X-RestOS-Web-Session": "1",
            },
        )
    assert missing.status_code == wrong.status_code == 403
    assert missing.json() == wrong.json() == {"detail": {"code": "permission_denied"}}
    assert missing.headers["cache-control"] == "private, no-store"


def test_disabled_sms_returns_controlled_503_and_rolls_back(monkeypatch):
    class Verification:
        def __init__(self, **_):
            pass

        async def request_code(self, _request):
            raise SmsDeliveryFailed("provider disabled")

    monkeypatch.setattr(auth, "PhoneVerificationService", Verification)
    http, session = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/account/registration/sms/request",
            json={"phone": "+79991234567"},
            headers=headers(),
        )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "sms_temporarily_unavailable"}}
    assert session.rollbacks == 1 and session.commits == 0
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("unknown", [False, True])
def test_login_masks_wrong_password_and_unknown_phone(monkeypatch, unknown):
    class Service:
        async def login(self, _request):
            raise StandaloneAccountAuthUnavailable("internal distinction")

    monkeypatch.setattr(auth, "_auth_service", lambda _session: Service())
    http, session = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/account/login",
            json={
                "phone": "+79990000001" if unknown else "+79990000002",
                "password": "wrong password",
                "app_instance_id": str(uuid4()),
                "platform": "web",
                "public_key": "cHVibGljLWtleQ==",
            },
            headers=headers(),
        )
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "authentication_unavailable"}}
    assert session.rollbacks == 1
    assert "set-cookie" not in response.headers


def test_login_success_sets_only_secure_httponly_refresh_cookie(monkeypatch):
    expected = auth_result()

    class Service:
        async def login(self, _request):
            return expected

    class Tokens:
        def __init__(self, *_args, **_kwargs):
            pass

        async def issue(self, _request):
            return IssuedAccountAccessToken("synthetic-access-token", NOW + timedelta(minutes=10))

    monkeypatch.setattr(auth, "_auth_service", lambda _session: Service())
    monkeypatch.setattr(auth, "AccountAccessTokenService", Tokens)
    http, session = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/account/login",
            json={
                "phone": "+79990000003",
                "password": "correct horse battery",
                "app_instance_id": str(uuid4()),
                "platform": "web",
                "public_key": "cHVibGljLWtleQ==",
            },
            headers=headers(),
        )
    assert response.status_code == 200 and session.commits == 1
    assert response.json()["access_token"] == "synthetic-access-token"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert expected.refresh_token not in response.text
    assert response.headers["cache-control"] == "private, no-store"


def test_password_reset_completion_clears_cookie_and_is_no_store(monkeypatch):
    class Service:
        async def reset_password(self, _request):
            return ResetStandaloneAccountPasswordResult(uuid4(), 2, 3)

    monkeypatch.setattr(auth, "_auth_service", lambda _session: Service())
    http, session = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/account/password-reset/complete",
            json={
                "challenge_id": str(uuid4()),
                "phone": "+79990000004",
                "new_password": "new correct horse battery",
            },
            headers=headers(),
        )
    assert response.status_code == 200 and response.json() == {"reset": True}
    assert session.commits == 1
    assert response.headers["cache-control"] == "private, no-store"
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_sms_aero_sign_contract_is_exact(monkeypatch):
    monkeypatch.setattr(auth.config, "APP_ENV", "production")
    monkeypatch.setattr(auth.config, "SMS_PROVIDER", "smsaero")
    monkeypatch.setattr(auth.config, "SMS_AERO_EMAIL", "runtime-only@example.test")
    monkeypatch.setattr(auth.config, "SMS_AERO_API_KEY", "runtime-only-key")
    monkeypatch.setattr(auth.config, "SMS_AERO_BASE_URL", "https://gate.smsaero.ru")
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN", "pilot.restos.space")
    monkeypatch.setattr(auth.config, "SMS_AERO_SIGN", "wrong")
    with pytest.raises(RuntimeError, match="SMS_AERO_SIGN"):
        auth.config.validate_production_security()
