"""HTTP boundary tests for additive invited Account registration."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.routers import account_invitation_auth as auth
from app.internal.services.invited_employee_registration_service import (
    InvitedEmployeeRegistrationUnavailable,
)
from app.internal.services.phone_verification_service import (
    InvalidOrUnavailablePhoneChallenge,
    PhoneVerificationCodeRequested,
    PhoneVerificationCooldown,
    PhoneVerificationRejected,
    PhoneVerificationSucceeded,
    SmsDeliveryFailed,
)


NOW = datetime.now(timezone.utc)
SECRETS = b"x" * 32


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, invitation=None):
        self.invitation = invitation
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _statement):
        return ScalarResult(self.invitation)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeSender:
    def __init__(self):
        self.messages = []

    async def send_verification_code(self, **message):
        self.messages.append(message)


def client(monkeypatch, session=None, sender=None):
    session = session or FakeSession()
    sender = sender or FakeSender()
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_INVITATION_PEPPER", "i" * 32)
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_PHONE_PEPPER", "p" * 32)
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_CODE_PEPPER", "c" * 32)
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_SESSION_PEPPER", "s" * 32)
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN", "example.test")

    async def session_override():
        yield session

    def sender_override():
        return sender

    app = FastAPI()
    auth.configure_account_auth_http_security(app)
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_account_auth_session] = session_override
    app.dependency_overrides[auth.get_sms_sender] = sender_override
    return TestClient(app), session, sender


def invitation():
    return SimpleNamespace(
        id=uuid4(),
        employee_profile_id=uuid4(),
        expires_at=NOW + timedelta(hours=1),
    )


def test_unknown_invitation_is_non_enumerating(monkeypatch):
    http, _, sender = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/request",
            json={"invitation_code": "123456", "phone": "+79990001122"},
        )
    assert response.status_code == 202
    assert response.json()["challenge_id"]
    assert sender.messages == []
    assert response.headers["cache-control"] == "no-store"


def test_request_success_commits_and_returns_public_shape(monkeypatch):
    expected = PhoneVerificationCodeRequested(
        uuid4(), NOW + timedelta(minutes=5), NOW + timedelta(minutes=1)
    )

    class Service:
        def __init__(self, **_):
            pass

        async def request_code(self, _request):
            return expected

    monkeypatch.setattr(auth, "PhoneVerificationService", Service)
    http, session, _ = client(monkeypatch, FakeSession(invitation()))
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/request",
            json={"invitation_code": "123456", "phone": "+79990001122"},
        )
    assert response.status_code == 202
    assert response.json()["challenge_id"] == str(expected.challenge_id)
    assert session.commits == 1
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (PhoneVerificationCooldown("cooldown"), 429, "verification_cooldown"),
        (SmsDeliveryFailed("sender"), 503, "sms_temporarily_unavailable"),
    ],
)
def test_request_maps_controlled_errors(monkeypatch, error, status_code, code):
    class Service:
        def __init__(self, **_):
            pass

        async def request_code(self, _request):
            raise error

    monkeypatch.setattr(auth, "PhoneVerificationService", Service)
    http, session, _ = client(monkeypatch, FakeSession(invitation()))
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/request",
            json={"invitation_code": "123456", "phone": "+79990001122"},
        )
    assert response.status_code == status_code
    assert response.json() == {"detail": {"code": code}}
    assert session.rollbacks == 1
    assert response.headers["cache-control"] == "no-store"


def test_verify_success_is_empty_204(monkeypatch):
    class Service:
        def __init__(self, **_):
            pass

        async def verify_code(self, request):
            return PhoneVerificationSucceeded(
                request.challenge_id,
                "invitation_registration",
                None,
                uuid4(),
                uuid4(),
                NOW,
            )

    monkeypatch.setattr(auth, "PhoneVerificationService", Service)
    http, session, _ = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/verify",
            json={
                "challenge_id": str(uuid4()),
                "phone": "+79990001122",
                "code": "012345",
            },
        )
    assert response.status_code == 204
    assert response.content == b""
    assert session.commits == 1
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("code", ["١٢٣٤٥٦", "12345", "1234567", "12 345", "abcdef"])
def test_verify_rejects_non_ascii_or_non_six_digit_codes(monkeypatch, code):
    http, _, _ = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/verify",
            json={
                "challenge_id": str(uuid4()),
                "phone": "+79990001122",
                "code": code,
            },
        )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_request"}}
    assert response.headers["cache-control"] == "no-store"


def test_verify_masks_unavailable_challenge(monkeypatch):
    class Service:
        def __init__(self, **_):
            pass

        async def verify_code(self, _request):
            raise InvalidOrUnavailablePhoneChallenge("internal reason")

    monkeypatch.setattr(auth, "PhoneVerificationService", Service)
    http, session, _ = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/verify",
            json={
                "challenge_id": str(uuid4()),
                "phone": "+79990001122",
                "code": "012345",
            },
        )
    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "verification_unavailable"}}
    assert "internal reason" not in response.text
    assert session.rollbacks == 1


def test_verify_locked_has_stable_public_code(monkeypatch):
    class Service:
        def __init__(self, **_):
            pass

        async def verify_code(self, _request):
            return PhoneVerificationRejected("locked", 0)

    monkeypatch.setattr(auth, "PhoneVerificationService", Service)
    http, _, _ = client(monkeypatch)
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/verify",
            json={
                "challenge_id": str(uuid4()),
                "phone": "+79990001122",
                "code": "012345",
            },
        )
    assert response.status_code == 423
    assert response.json() == {"detail": {"code": "verification_locked"}}


def registration_json():
    return {
        "invitation_code": "123456",
        "phone_verification_challenge_id": str(uuid4()),
        "phone": "+79990001122",
        "display_name": "Анна",
        "password": "safe-password-123",
        "app_instance_id": str(uuid4()),
        "platform": "ios",
        "device_display_name": "iPhone",
        "device_public_key": "cHVibGljLWtleQ==",
    }


def test_register_success_returns_only_public_result(monkeypatch):
    result = SimpleNamespace(
        account_id=uuid4(),
        employee_profile_id=uuid4(),
        employee_assignment_id=uuid4(),
        company_id=uuid4(),
        device_id=uuid4(),
        session_id=uuid4(),
        refresh_token="selector.secret",
        display_name="Анна",
    )

    class Service:
        def __init__(self, *_args, **_kwargs):
            pass

        async def register(self, _request):
            return result

    monkeypatch.setattr(auth, "InvitedEmployeeRegistrationService", Service)
    http, session, _ = client(monkeypatch)
    with http:
        response = http.post("/api/v1/auth/invitations/register", json=registration_json())
    assert response.status_code == 200
    assert response.json()["refresh_token"] == "selector.secret"
    assert set(response.json()) == {
        "account_id", "employee_profile_id", "employee_assignment_id",
        "company_id", "device_id", "session_id", "refresh_token", "display_name",
    }
    assert session.commits == 1
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "field", ["company_id", "venue_id", "position_id", "access_profile_id", "permissions", "scope"]
)
def test_register_rejects_privilege_fields(monkeypatch, field):
    payload = registration_json()
    payload[field] = str(uuid4())
    http, _, _ = client(monkeypatch)
    with http:
        response = http.post("/api/v1/auth/invitations/register", json=payload)
    assert response.status_code == 422


def test_registration_error_rolls_back_and_hides_secrets(monkeypatch):
    class Service:
        def __init__(self, *_args, **_kwargs):
            pass

        async def register(self, _request):
            raise InvitedEmployeeRegistrationUnavailable(
                "uq_internal_secret refresh_token=hidden"
            )

    monkeypatch.setattr(auth, "InvitedEmployeeRegistrationService", Service)
    http, session, _ = client(monkeypatch)
    payload = registration_json()
    with http:
        response = http.post("/api/v1/auth/invitations/register", json=payload)
    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "registration_unavailable"}}
    assert payload["password"] not in response.text
    assert "uq_internal_secret" not in response.text
    assert session.rollbacks == 1


def test_validation_response_never_reflects_auth_secrets(monkeypatch):
    payload = registration_json()
    payload.update(
        {
            "invitation_code": "secret-invitation",
            "phone": "+79998887766",
            "password": "secret-password-value",
            "device_public_key": "secret-public-key",
        }
    )
    http, _, _ = client(monkeypatch)
    with http:
        response = http.post("/api/v1/auth/invitations/register", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_request"}}
    for secret in payload.values():
        if isinstance(secret, str):
            assert secret not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_unexpected_500_is_safe_and_not_cacheable(monkeypatch):
    class BrokenSession(FakeSession):
        async def execute(self, _statement):
            raise RuntimeError("database details must stay private")

    http, _, _ = client(monkeypatch, BrokenSession())
    with http:
        response = http.post(
            "/api/v1/auth/invitations/sms/request",
            json={"invitation_code": "123456", "phone": "+79990001122"},
        )
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_error"}}
    assert "database details" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_legacy_validation_response_keeps_fastapi_shape(monkeypatch):
    http, _, _ = client(monkeypatch)

    @http.app.get("/legacy/{item_id}")
    async def legacy(item_id: int):
        return {"item_id": item_id}

    with http:
        response = http.get("/legacy/not-an-integer")
    assert response.status_code == 422
    assert isinstance(response.json().get("detail"), list)
    assert "cache-control" not in response.headers


def test_openapi_response_schemas_do_not_expose_digest_or_password(monkeypatch):
    http, _, _ = client(monkeypatch)
    schema = http.app.openapi()
    response_schema_names = {
        "SmsRequested", "RegistrationResponse", "PublicError"
    }
    text = " ".join(
        str(schema["components"]["schemas"][name]) for name in response_schema_names
    ).lower()
    assert "password" not in text
    assert "digest" not in text
    assert "constraint" not in text
