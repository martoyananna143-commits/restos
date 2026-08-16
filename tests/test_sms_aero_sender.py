"""Network-free contract tests for the SMS Aero adapter and provider factory."""

import base64
from datetime import datetime, timedelta, timezone
import logging
from types import SimpleNamespace
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from app.api.routers import account_invitation_auth as auth
from app.infra.sms import SmsAeroSender
from app.internal.services.phone_verification_service import SmsDeliveryFailed
from app.internal.services.phone_verification_service import (
    PhoneVerificationCodeRequested,
)
from app.settings import config


EMAIL = "api@example.test"
API_KEY = "test-api-key-not-real"
SIGN = "SMS Aero"
BASE_URL = "https://gate.smsaero.test"


def sender(handler, timeout=2.0):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        SmsAeroSender(
            client,
            email=EMAIL,
            api_key=API_KEY,
            sign=SIGN,
            base_url=BASE_URL,
            timeout_seconds=timeout,
        ),
        client,
    )


@pytest.mark.asyncio
async def test_request_contract_auth_and_success():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"success": True, "data": {"id": 1}})

    adapter, client = sender(handler)
    await adapter.send_verification_code(
        "+79990001122", "012345", "invitation_registration", 300, "restos.app"
    )
    await client.aclose()
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == f"{BASE_URL}/v2/sms/send"
    assert API_KEY not in str(request.url)
    expected_auth = base64.b64encode(f"{EMAIL}:{API_KEY}".encode()).decode()
    assert request.headers["authorization"] == f"Basic {expected_auth}"
    body = request.content.decode()
    assert "number=79990001122" in body
    assert "sign=SMS+Aero" in body
    assert "%40restos.app+%23012345" in body
    assert "012345" in body
    assert API_KEY not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"success": False, "message": "rejected"}),
        httpx.Response(
            200, json={"success": False, "message": "insufficient balance"}
        ),
        httpx.Response(401, json={"success": False}),
        httpx.Response(403, json={"success": False}),
        httpx.Response(429, json={"success": False}),
        httpx.Response(500, json={"success": False}),
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=["malformed"]),
    ],
)
async def test_provider_and_http_failures_are_controlled(response):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return response

    adapter, client = sender(handler)
    with pytest.raises(SmsDeliveryFailed, match="SMS delivery failed") as caught:
        await adapter.send_verification_code(
            "+79990001122", "012345", "invitation_registration", 300, "restos.app"
        )
    await client.aclose()
    assert calls == 1
    assert API_KEY not in str(caught.value)
    assert "+79990001122" not in str(caught.value)
    assert "012345" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("timeout"),
        httpx.ConnectError("network"),
    ],
)
async def test_network_failures_are_controlled_without_retry(error):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        raise error

    adapter, client = sender(handler)
    with pytest.raises(SmsDeliveryFailed):
        await adapter.send_verification_code(
            "+79990001122", "012345", "invitation_registration", 300, "restos.app"
        )
    await client.aclose()
    assert calls == 1


@pytest.mark.parametrize(
    "field",
    ["email", "api_key", "sign", "base_url"],
)
def test_incomplete_adapter_configuration_is_rejected(field):
    values = {
        "email": EMAIL,
        "api_key": API_KEY,
        "sign": SIGN,
        "base_url": BASE_URL,
    }
    values[field] = ""
    with pytest.raises(ValueError, match="configuration is incomplete"):
        SmsAeroSender(httpx.AsyncClient(), timeout_seconds=2.0, **values)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://gate.smsaero.test",
        "https://user:secret@gate.smsaero.test",
        "https://gate.smsaero.test?api_key=secret",
    ],
)
def test_adapter_requires_safe_https_base_url(base_url):
    with pytest.raises(ValueError, match="safe HTTPS URL"):
        SmsAeroSender(
            httpx.AsyncClient(),
            email=EMAIL,
            api_key=API_KEY,
            sign=SIGN,
            base_url=base_url,
            timeout_seconds=2.0,
        )


def _safe_production_config(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "ACCOUNT_GROUP_INVITATION_PEPPER", "g" * 64)
    monkeypatch.setattr(config, "JWT_SECRET_KEY", "j" * 64)
    monkeypatch.setattr(config, "WEBAPP_SECRET_KEY", "w" * 64)
    monkeypatch.setattr(config, "DEFAULT_ADMIN_PASSWORD", "Strong-Test-Password-20")
    monkeypatch.setattr(config, "INTERNAL_API_KEY", "i" * 64)
    monkeypatch.setattr(config, "CORS_ORIGINS", ["https://restos.test"])
    monkeypatch.setattr(config, "CORS_ALLOW_CREDENTIALS", True)
    monkeypatch.setattr(config, "WEBAUTHN_RP_ID", "passkeys.example.com")
    monkeypatch.setattr(config, "WEBAUTHN_RP_NAME", "RestOS Test")
    monkeypatch.setattr(
        config,
        "WEBAUTHN_ALLOWED_ORIGINS",
        ["https://passkeys.example.com"],
    )
    monkeypatch.setattr(config, "WEBAUTHN_CHALLENGE_TTL_SECONDS", 300)
    monkeypatch.setattr(config, "WEBAUTHN_MAX_VERIFY_ATTEMPTS", 3)
    monkeypatch.setattr(config, "SMS_AERO_EMAIL", EMAIL)
    monkeypatch.setattr(config, "SMS_AERO_API_KEY", API_KEY)
    monkeypatch.setattr(config, "SMS_AERO_SIGN", SIGN)
    monkeypatch.setattr(config, "SMS_AERO_BASE_URL", BASE_URL)
    monkeypatch.setattr(config, "SMS_HTTP_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(config, "ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN", "restos.test")


def test_production_smsaero_configuration_is_validated_without_secret_values(
    monkeypatch,
):
    _safe_production_config(monkeypatch)
    monkeypatch.setattr(config, "SMS_PROVIDER", "smsaero")
    config.validate_production_security()

    monkeypatch.setattr(config, "SMS_AERO_API_KEY", "")
    with pytest.raises(RuntimeError) as caught:
        config.validate_production_security()
    message = str(caught.value)
    assert "SMS_AERO_API_KEY" in message
    assert API_KEY not in message
    assert EMAIL not in message


@pytest.mark.parametrize("provider", ["mock", "unknown-provider"])
def test_production_rejects_non_smsaero_provider(monkeypatch, provider):
    _safe_production_config(monkeypatch)
    monkeypatch.setattr(config, "SMS_PROVIDER", provider)
    with pytest.raises(RuntimeError, match="SMS_PROVIDER"):
        config.validate_production_security()


def factory_client(monkeypatch, provider):
    monkeypatch.setattr(auth.config, "SMS_PROVIDER", provider)
    monkeypatch.setattr(auth.config, "SMS_AERO_EMAIL", EMAIL)
    monkeypatch.setattr(auth.config, "SMS_AERO_API_KEY", API_KEY)
    monkeypatch.setattr(auth.config, "SMS_AERO_SIGN", SIGN)
    monkeypatch.setattr(auth.config, "SMS_AERO_BASE_URL", BASE_URL)
    monkeypatch.setattr(auth.config, "SMS_HTTP_TIMEOUT_SECONDS", 2.0)
    app = FastAPI()
    auth.configure_account_auth_http_security(app)

    @app.get(f"{auth.AUTH_PREFIX}/factory")
    async def factory(sender=Depends(auth.get_sms_sender)):
        return {"type": type(sender).__name__}

    return app


def test_disabled_and_unknown_provider_are_safe(monkeypatch):
    disabled = factory_client(monkeypatch, "disabled")
    disabled.state.sms_http_client = httpx.AsyncClient()
    with TestClient(disabled) as http:
        response = http.get(f"{auth.AUTH_PREFIX}/factory")
    assert response.status_code == 200
    assert response.json() == {"type": "UnconfiguredSmsSender"}

    unknown = factory_client(monkeypatch, "unknown-provider")
    unknown.state.sms_http_client = httpx.AsyncClient()
    with TestClient(unknown) as http:
        response = http.get(f"{auth.AUTH_PREFIX}/factory")
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "sms_temporarily_unavailable"}}
    assert API_KEY not in response.text


def test_smsaero_factory_uses_app_lifecycle_client(monkeypatch):
    app = factory_client(monkeypatch, "smsaero")
    shared = httpx.AsyncClient()
    app.state.sms_http_client = shared
    with TestClient(app) as http:
        response = http.get(f"{auth.AUTH_PREFIX}/factory")
    assert response.status_code == 200
    assert response.json() == {"type": "SmsAeroSender"}


@pytest.mark.asyncio
async def test_failure_does_not_log_phone_code_or_key(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(_request):
        return httpx.Response(
            200, json={"success": False, "message": "provider rejected request"}
        )

    adapter, client = sender(handler)
    with pytest.raises(SmsDeliveryFailed):
        await adapter.send_verification_code(
            "+79990001122", "012345", "invitation_registration", 300, "restos.app"
        )
    await client.aclose()
    assert API_KEY not in caplog.text
    assert "+79990001122" not in caplog.text
    assert "012345" not in caplog.text


def test_http_request_code_uses_configured_smsaero_mock(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"success": True, "data": {"id": 1}})

    class ScalarResult:
        def scalar_one_or_none(self):
            return SimpleNamespace(id=uuid4(), employee_profile_id=uuid4())

    class Session:
        async def execute(self, _statement):
            return ScalarResult()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    class Verification:
        def __init__(self, **kwargs):
            self.sender = kwargs["sender"]

        async def request_code(self, request):
            await self.sender.send_verification_code(
                request.phone,
                "012345",
                request.purpose,
                300,
                "restos.app",
            )
            now = datetime.now(timezone.utc)
            return PhoneVerificationCodeRequested(
                uuid4(), now + timedelta(minutes=5), now + timedelta(minutes=1)
            )

    monkeypatch.setattr(auth, "PhoneVerificationService", Verification)
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_INVITATION_PEPPER", "i" * 32)
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_PHONE_PEPPER", "p" * 32)
    monkeypatch.setattr(auth.config, "ACCOUNT_AUTH_CODE_PEPPER", "c" * 32)
    app = factory_client(monkeypatch, "smsaero")
    app.include_router(auth.router)
    app.state.sms_http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )

    async def session_override():
        yield Session()

    app.dependency_overrides[auth.get_account_auth_session] = session_override
    with TestClient(app) as http:
        response = http.post(
            "/api/v1/auth/invitations/sms/request",
            json={
                "invitation_code": "123456",
                "phone": "+79990001122",
                "personal_data_consent": True,
                "personal_data_consent_version": "restos-pd-consent-2026-08-10-v1",
                "authorization_sms_consent": True,
                "authorization_sms_consent_version": "restos-auth-sms-consent-2026-08-10-v1",
            },
        )
    assert response.status_code == 202
    assert len(requests) == 1
    assert requests[0].url == f"{BASE_URL}/v2/sms/send"
