"""P0-LEGAL version, consent admission, persistence, and rollback tests."""

from datetime import datetime, timezone
import os

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.routers.account_standalone_auth import (
    PasswordResetRequest,
    RegistrationSmsRequest,
    StandaloneRegistrationRequest,
)
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.internal.services.account_legal_contract import (
    AUTH_SMS_CONSENT_VERSION,
    PASSWORD_RECOVERY_OTP_MESSAGE_TYPE,
    PD_CONSENT_DOCUMENT_SHA256,
    PD_CONSENT_VERSION,
    REGISTRATION_OTP_MESSAGE_TYPE,
    REGISTRATION_SMS_COPY_SHA256,
    AccountLegalVersionMismatch,
    AuthorizationSmsConsent,
    RegistrationSmsConsent,
    require_registration_sms_consent,
)
from app.internal.services.phone_verification_service import (
    PhoneVerificationService,
    RequestPhoneVerificationCode,
    SmsDeliveryFailed,
)


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
PHONE_PEPPER = b"legal-phone-pepper-for-tests!!!!"
CODE_PEPPER = b"legal-code-pepper-for-tests!!!!!"


class Sender:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    async def send_verification_code(self, **_):
        self.calls += 1
        if self.fail:
            raise RuntimeError("controlled provider failure")


def registration_consent(**changes) -> RegistrationSmsConsent:
    values = dict(
        personal_data_consent=True,
        personal_data_consent_version=PD_CONSENT_VERSION,
        authorization_sms_consent=True,
        authorization_sms_consent_version=AUTH_SMS_CONSENT_VERSION,
    )
    values.update(changes)
    return RegistrationSmsConsent(**values)


def test_signup_dtos_are_minimal_and_require_explicit_consent():
    assert "city" not in StandaloneRegistrationRequest.model_fields
    assert "date_of_birth" not in StandaloneRegistrationRequest.model_fields
    assert "display_name" in StandaloneRegistrationRequest.model_fields
    assert RegistrationSmsRequest.model_fields["personal_data_consent"].is_required()
    assert RegistrationSmsRequest.model_fields["authorization_sms_consent"].is_required()
    assert "personal_data_consent" not in PasswordResetRequest.model_fields
    assert PasswordResetRequest.model_fields["authorization_sms_consent"].is_required()


@pytest.mark.parametrize(
    "changes",
    [
        {"personal_data_consent": False},
        {"authorization_sms_consent": False},
        {"personal_data_consent_version": "stale"},
        {"authorization_sms_consent_version": "stale"},
    ],
)
def test_registration_consent_fails_closed(changes):
    with pytest.raises(AccountLegalVersionMismatch):
        require_registration_sms_consent(registration_consent(**changes))


@pytest.mark.asyncio
async def test_registration_consent_is_server_timestamped_and_hashed():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    async with AsyncSession(bind=connection, expire_on_commit=False) as session:
        sender = Sender()
        verification = PhoneVerificationService(
            session,
            sender,
            PHONE_PEPPER,
            CODE_PEPPER,
            "pilot.restos.space",
            code_generator=lambda: "012345",
        )
        result = await verification.request_code(
            RequestPhoneVerificationCode(
                purpose="account_registration",
                phone="+79990001234",
                now=NOW,
                registration_sms_consent=registration_consent(),
                auth_sms_message_type=REGISTRATION_OTP_MESSAGE_TYPE,
            )
        )
        stored = await session.get(PhoneVerificationChallenge, result.challenge_id)
        assert stored.pd_consent_version == PD_CONSENT_VERSION
        assert stored.pd_consent_document_sha256 == PD_CONSENT_DOCUMENT_SHA256
        assert stored.pd_consent_accepted_at == NOW
        assert stored.auth_sms_consent_version == AUTH_SMS_CONSENT_VERSION
        assert stored.auth_sms_consent_copy_sha256 == REGISTRATION_SMS_COPY_SHA256
        assert stored.auth_sms_consent_accepted_at == NOW
        assert stored.auth_sms_message_type == REGISTRATION_OTP_MESSAGE_TYPE
        assert sender.calls == 1
    await transaction.rollback()
    await connection.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_delivery_rolls_back_consent_and_challenge():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    async with AsyncSession(bind=connection, expire_on_commit=False) as session:
        before = (
            await session.execute(select(func.count(PhoneVerificationChallenge.id)))
        ).scalar_one()
        sender = Sender(fail=True)
        verification = PhoneVerificationService(
            session,
            sender,
            PHONE_PEPPER,
            CODE_PEPPER,
            "pilot.restos.space",
            code_generator=lambda: "012345",
        )
        with pytest.raises(SmsDeliveryFailed):
            await verification.request_code(
                RequestPhoneVerificationCode(
                    purpose="password_reset",
                    phone="+79990004321",
                    now=NOW,
                    authorization_sms_consent=AuthorizationSmsConsent(
                        authorization_sms_consent=True,
                        authorization_sms_consent_version=AUTH_SMS_CONSENT_VERSION,
                    ),
                    auth_sms_message_type=PASSWORD_RECOVERY_OTP_MESSAGE_TYPE,
                )
            )
        after = (
            await session.execute(select(func.count(PhoneVerificationChallenge.id)))
        ).scalar_one()
        assert after == before
        assert sender.calls == 1
    await transaction.rollback()
    await connection.close()
    await engine.dispose()
