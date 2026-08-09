"""End-to-end HTTP boundary test with PostgreSQL and a controlled SMS sender."""

import base64
import os
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.routers import account_invitation_auth as invitation_auth
from app.api.routers import account_standalone_auth as auth
from app.infra.database.models.account import Account, AccountSession
from app.internal.services.device_registration_challenge_service import (
    canonical_account_registration_message,
)


class ControlledSmsSender:
    def __init__(self):
        self.messages = []

    async def send_verification_code(self, **message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_full_registration_login_and_password_reset_http_flow(monkeypatch):
    phone = f"+7999{uuid4().int % 10_000_000:07d}"
    engine = create_async_engine(os.environ["DATABASE_URL"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    sender = ControlledSmsSender()
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
    ):
        monkeypatch.setattr(auth.config, name, value)
        monkeypatch.setattr(invitation_auth.config, name, value)

    async def session_override():
        async with sessions() as session:
            yield session

    app = FastAPI()
    invitation_auth.configure_account_auth_http_security(app)
    app.include_router(auth.router)
    app.dependency_overrides[auth.get_account_auth_session] = session_override
    app.dependency_overrides[auth.get_sms_sender] = lambda: sender
    headers = {
        "Origin": "https://testserver",
        "X-RestOS-Web-Session": "1",
    }
    key = ec.generate_private_key(ec.SECP256R1())
    public_key = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    app_instance_id = uuid4()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver"
    ) as http:
        requested = await http.post(
            "/api/v1/auth/account/registration/sms/request",
            json={"phone": phone},
            headers=headers,
        )
        assert requested.status_code == 202 and len(sender.messages) == 1
        challenge_id = requested.json()["challenge_id"]
        verified = await http.post(
            "/api/v1/auth/account/registration/sms/verify",
            json={
                "challenge_id": challenge_id,
                "phone": phone,
                "code": sender.messages[-1]["code"],
            },
            headers=headers,
        )
        assert verified.status_code == 200 and verified.json() == {"verified": True}
        device = await http.post(
            "/api/v1/auth/account/registration/device/challenge",
            json={
                "phone_verification_challenge_id": challenge_id,
                "phone": phone,
                "app_instance_id": str(app_instance_id),
                "platform": "web",
                "public_key": base64.b64encode(public_key).decode("ascii"),
            },
            headers=headers,
        )
        assert device.status_code == 200
        device_body = device.json()
        nonce = base64.urlsafe_b64decode(device_body["nonce"] + "=")
        signature = key.sign(
            canonical_account_registration_message(
                device_challenge_id=UUID(device_body["device_challenge_id"]),
                phone_challenge_id=UUID(challenge_id),
                app_instance_id=app_instance_id,
                platform="web",
                nonce=nonce,
            ),
            ec.ECDSA(hashes.SHA256()),
        )
        registered = await http.post(
            "/api/v1/auth/account/registration/complete",
            json={
                "phone_verification_challenge_id": challenge_id,
                "phone": phone,
                "display_name": "Pilot Account",
                "password": "correct horse battery",
                "app_instance_id": str(app_instance_id),
                "platform": "web",
                "device_challenge_id": device_body["device_challenge_id"],
                "device_challenge_nonce": device_body["nonce"],
                "device_challenge_signature": base64.urlsafe_b64encode(signature)
                .rstrip(b"=")
                .decode("ascii"),
            },
            headers=headers,
        )
        assert registered.status_code == 200
        assert registered.json()["access_token"]
        assert "httponly" in registered.headers["set-cookie"].lower()
        account_id = registered.json()["account_id"]
        first_session_id = registered.json()["session_id"]

        login_key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        logged_in = await http.post(
            "/api/v1/auth/account/login",
            json={
                "phone": phone,
                "password": "correct horse battery",
                "app_instance_id": str(uuid4()),
                "platform": "web",
                "public_key": base64.b64encode(login_key).decode("ascii"),
            },
            headers=headers,
        )
        assert logged_in.status_code == 200
        second_session_id = logged_in.json()["session_id"]

        reset_requested = await http.post(
            "/api/v1/auth/account/password-reset/sms/request",
            json={"phone": phone},
            headers=headers,
        )
        assert reset_requested.status_code == 202 and len(sender.messages) == 2
        reset_id = reset_requested.json()["challenge_id"]
        reset_verified = await http.post(
            "/api/v1/auth/account/password-reset/sms/verify",
            json={
                "challenge_id": reset_id,
                "phone": phone,
                "code": sender.messages[-1]["code"],
            },
            headers=headers,
        )
        assert reset_verified.status_code == 200
        reset = await http.post(
            "/api/v1/auth/account/password-reset/complete",
            json={
                "challenge_id": reset_id,
                "phone": phone,
                "new_password": "new correct horse battery",
            },
            headers=headers,
        )
        assert reset.status_code == 200 and reset.json() == {"reset": True}

    async with AsyncSession(engine) as verify:
        account = await verify.get(Account, UUID(account_id))
        stored_sessions = list(
            (
                await verify.execute(
                    select(AccountSession).where(
                        AccountSession.id.in_(
                            [
                                UUID(first_session_id),
                                UUID(second_session_id),
                            ]
                        )
                    )
                )
            ).scalars()
        )
        assert account.security_version == 2
        assert {item.status for item in stored_sessions} == {"revoked"}
    await engine.dispose()
