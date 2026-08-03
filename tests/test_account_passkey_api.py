"""Focused HTTP/OpenAPI tests for the Stage 22A passkey boundary."""

from datetime import datetime, timedelta, timezone
import base64
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.account_auth import get_current_account_principal
from app.api.main import create_app
from app.api.routers import account_invitation_auth, account_passkeys
from app.internal.services.account_access_token_service import (
    CurrentAccountPrincipal,
)
from app.internal.services.account_passkey_service import (
    AccountPasskeyUnavailable,
    PasskeySummary,
)


ORIGIN = "https://restos.test"
HEADERS = {"Origin": ORIGIN, "X-RestOS-Web-Session": "1"}
PREFIX = "/api/v1/auth/web/passkeys"


def _configured_app(monkeypatch):
    monkeypatch.setattr(
        account_invitation_auth.config, "ACCOUNT_WEB_ALLOWED_ORIGINS", [ORIGIN]
    )
    monkeypatch.setattr(account_invitation_auth.config, "APP_ENV", "test")
    return create_app()


def test_openapi_has_exactly_six_protected_passkey_routes(monkeypatch):
    app = _configured_app(monkeypatch)
    schema = app.openapi()
    operations = sorted(
        (method.upper(), path)
        for path, item in schema["paths"].items()
        if path.startswith(PREFIX)
        for method in item
        if method.lower() in {"get", "post", "delete"}
    )
    assert operations == [
        ("DELETE", f"{PREFIX}/{{identity_id}}"),
        ("GET", PREFIX),
        ("POST", f"{PREFIX}/authentication/options"),
        ("POST", f"{PREFIX}/authentication/verify"),
        ("POST", f"{PREFIX}/registration/options"),
        ("POST", f"{PREFIX}/registration/verify"),
    ]
    assert schema["paths"][f"{PREFIX}/registration/options"]["post"][
        "security"
    ]
    assert schema["paths"][f"{PREFIX}/registration/verify"]["post"][
        "security"
    ]
    auth_options = json.dumps(
        schema["paths"][f"{PREFIX}/authentication/options"],
        sort_keys=True,
    ).lower()
    assert "account_id" not in auth_options
    assert "email" not in auth_options
    assert "phone" not in auth_options


def test_passkey_openapi_schemas_exclude_server_controlled_and_secret_fields(
    monkeypatch,
):
    schema = _configured_app(monkeypatch).openapi()
    passkey_schema_names = {
        "AuthenticationOptionsRequest",
        "AuthenticationVerifyRequest",
        "AuthenticationVerifyResponse",
        "DeviceContext",
        "PasskeyOptionsResponse",
        "PasskeyResponse",
        "RegistrationVerifyRequest",
        "RegistrationVerifyResponse",
    }
    serialized = json.dumps(
        {
            name: schema["components"]["schemas"][name]
            for name in passkey_schema_names
        },
        sort_keys=True,
    ).lower()
    for forbidden in (
        "private_key",
        "challenge_digest",
        "credential_public_key",
        "device_public_key_digest",
        "refresh_token",
        "biometric",
        "sign_count",
        "session_id",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["/registration/options", "/registration/verify"])
async def test_registration_routes_reject_unauthenticated_with_no_store(
    monkeypatch, suffix
):
    app = _configured_app(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(PREFIX + suffix, headers=HEADERS, json={})
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "authentication_required"}}
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_authentication_options_schema_is_controlled_and_no_store(monkeypatch):
    app = _configured_app(monkeypatch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"{PREFIX}/authentication/options", headers=HEADERS, json={}
        )
    assert response.status_code == 422
    assert response.json() == {"detail": {"code": "invalid_request"}}
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_authentication_options_rate_limit_is_safe_and_bucket_scoped(
    monkeypatch,
):
    app = _configured_app(monkeypatch)
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

    async def session_override():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = session_override
    monkeypatch.setattr(account_passkeys.config, "WEBAUTHN_RP_ID", "restos.test")
    monkeypatch.setattr(account_passkeys.config, "WEBAUTHN_RP_NAME", "RestOS")
    monkeypatch.setattr(
        account_passkeys.config,
        "WEBAUTHN_ALLOWED_ORIGINS",
        [ORIGIN],
    )
    monkeypatch.setattr(
        account_passkeys.config,
        "ACCOUNT_AUTH_SESSION_PEPPER",
        "p" * 32,
    )
    monkeypatch.setattr(
        account_passkeys.config, "WEBAUTHN_CHALLENGE_TTL_SECONDS", 300
    )
    monkeypatch.setattr(
        account_passkeys.config, "WEBAUTHN_MAX_VERIFY_ATTEMPTS", 3
    )

    def device_body():
        public_key = ec.generate_private_key(
            ec.SECP256R1()
        ).public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return {
            "device": {
                "app_instance_id": str(uuid4()),
                "platform": "web",
                "display_name": "Browser",
                "public_key": base64.b64encode(public_key).decode("ascii"),
            }
        }

    limited_body = device_body()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
    ) as client:
        for _ in range(5):
            response = await client.post(
                f"{PREFIX}/authentication/options",
                headers=HEADERS,
                json=limited_body,
            )
            assert response.status_code == 200
        limited = await client.post(
            f"{PREFIX}/authentication/options",
            headers={**HEADERS, "X-Forwarded-For": "203.0.113.99"},
            json=limited_body,
        )
        independent = await client.post(
            f"{PREFIX}/authentication/options",
            headers=HEADERS,
            json=device_body(),
        )

    assert limited.status_code == 429
    assert limited.json() == {"detail": {"code": "too_many_requests"}}
    assert limited.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in limited.headers
    serialized = limited.text.lower()
    for forbidden in (
        "pending",
        "bucket",
        "digest",
        "account_id",
        "credential",
        "email",
        "phone",
        "exception",
    ):
        assert forbidden not in serialized
    assert independent.status_code == 200
    await engine.dispose()


class _Session:
    async def commit(self):
        return None

    async def rollback(self):
        return None


class _PrincipalBoundService:
    def __init__(self, account_id, *, reject_revoke=False):
        self.account_id = account_id
        self.reject_revoke = reject_revoke
        self.seen_accounts = []

    async def list_passkeys(self, account_id, now):
        self.seen_accounts.append(account_id)
        return (
            PasskeySummary(
                identity_id=uuid4(),
                display_name="This device",
                transports=("internal",),
                backup_eligible=False,
                backup_state=False,
                created_at=now,
                last_used_at=None,
                status="active",
                revoked_at=None,
            ),
        )

    async def revoke_passkey(self, account_id, identity_id, now):
        self.seen_accounts.append(account_id)
        if self.reject_revoke:
            raise AccountPasskeyUnavailable("passkey operation is unavailable")
        return True


@pytest.mark.asyncio
async def test_list_and_revoke_use_only_current_account_principal(monkeypatch):
    app = _configured_app(monkeypatch)
    account_id = uuid4()
    principal = CurrentAccountPrincipal(
        account_id=account_id,
        session_id=uuid4(),
        device_id=uuid4(),
        security_version=1,
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    fake_service = _PrincipalBoundService(account_id)
    app.dependency_overrides[get_current_account_principal] = lambda: principal
    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = lambda: _Session()
    monkeypatch.setattr(account_passkeys, "_service", lambda _session: fake_service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        listed = await client.get(PREFIX, headers=HEADERS)
        revoked = await client.delete(f"{PREFIX}/{uuid4()}", headers=HEADERS)
    assert listed.status_code == 200
    assert "credential_public_key" not in listed.text
    assert revoked.status_code == 204
    assert fake_service.seen_accounts == [account_id, account_id]
    assert listed.headers["cache-control"] == "private, no-store"
    assert revoked.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_revoke_foreign_identity_is_indistinguishable_not_found(monkeypatch):
    app = _configured_app(monkeypatch)
    account_id = uuid4()
    principal = CurrentAccountPrincipal(
        account_id=account_id,
        session_id=uuid4(),
        device_id=uuid4(),
        security_version=1,
        token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    fake_service = _PrincipalBoundService(account_id, reject_revoke=True)
    app.dependency_overrides[get_current_account_principal] = lambda: principal
    app.dependency_overrides[
        account_invitation_auth.get_account_auth_session
    ] = lambda: _Session()
    monkeypatch.setattr(account_passkeys, "_service", lambda _session: fake_service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(f"{PREFIX}/{uuid4()}", headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "passkey_not_found"}}
    assert fake_service.seen_accounts == [account_id]
    assert response.headers["cache-control"] == "private, no-store"
