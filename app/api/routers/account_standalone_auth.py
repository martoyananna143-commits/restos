"""Strict web boundary for standalone Account registration and password auth."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.account_invitation_auth import (
    PublicError,
    SmsRequested,
    SmsSender,
    UnconfiguredSmsSender,
    _error,
    _secret,
    clear_web_refresh_cookie,
    get_account_auth_session,
    get_sms_sender,
    require_web_request,
    set_web_refresh_cookie,
)
from app.infra.database.models.account import AccountIdentity
from app.internal.services.account_access_token_service import (
    AccountAccessTokenConfigurationError,
    AccountAccessTokenService,
    IssueAccountAccessToken,
)
from app.internal.services.account_session_service import AccountSessionService
from app.internal.services.device_registration_challenge_service import (
    DeviceRegistrationChallengeError,
    DeviceRegistrationChallengeService,
    IssueAccountDeviceRegistrationChallenge,
)
from app.internal.services.phone_verification_service import (
    InvalidOrUnavailablePhoneChallenge,
    InvalidPhoneVerificationRequest,
    PhoneVerificationCooldown,
    PhoneVerificationRejected,
    PhoneVerificationService,
    PhoneVerificationUnavailable,
    RequestPhoneVerificationCode,
    SmsDeliveryFailed,
    VerifyPhoneVerificationCode,
)
from app.internal.services.standalone_account_auth_service import (
    InvalidStandaloneAccountAuthRequest,
    LoginStandaloneAccount,
    RegisterStandaloneAccount,
    ResetStandaloneAccountPassword,
    StandaloneAccountAuthError,
    StandaloneAccountAuthService,
)
from app.settings import config


router = APIRouter(prefix="/api/v1/auth/account", tags=["account-auth"])
_PLATFORMS = {"ios", "android", "web", "desktop", "unknown"}


class RegistrationSmsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=8, max_length=32)


class SmsVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    phone: str = Field(min_length=8, max_length=32)
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class SmsVerified(BaseModel):
    verified: Literal[True] = True


class AccountDeviceChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_verification_challenge_id: UUID
    phone: str = Field(min_length=8, max_length=32)
    app_instance_id: UUID
    platform: str
    public_key: str = Field(min_length=4, max_length=8192)


class AccountDeviceChallengeResponse(BaseModel):
    device_challenge_id: UUID
    nonce: str
    algorithm: Literal["ES256"]
    protocol: Literal["account-registration-v1"]
    expires_at: datetime


class StandaloneRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_verification_challenge_id: UUID
    phone: str = Field(min_length=8, max_length=32)
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=12, max_length=72)
    app_instance_id: UUID
    platform: str
    device_display_name: str | None = Field(default=None, max_length=255)
    device_challenge_id: UUID
    device_challenge_nonce: str = Field(min_length=43, max_length=43)
    device_challenge_signature: str = Field(min_length=8, max_length=256)


class PasswordLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=8, max_length=32)
    password: str = Field(min_length=1, max_length=72)
    app_instance_id: UUID
    platform: str
    device_display_name: str | None = Field(default=None, max_length=255)
    public_key: str = Field(min_length=4, max_length=8192)


class AccountAuthResponse(BaseModel):
    account_id: UUID
    device_id: UUID
    session_id: UUID
    access_token: str
    expires_at: datetime
    token_type: Literal["bearer"] = "bearer"
    display_name: str


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=8, max_length=32)


class PasswordResetCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    phone: str = Field(min_length=8, max_length=32)
    new_password: str = Field(min_length=12, max_length=72)


class PasswordResetResponse(BaseModel):
    reset: Literal[True] = True


def _verification_service(
    session: AsyncSession, sender: SmsSender
) -> PhoneVerificationService:
    return PhoneVerificationService(
        session=session,
        sender=sender,
        phone_pepper=_secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER"),
        code_pepper=_secret(config.ACCOUNT_AUTH_CODE_PEPPER, "CODE_PEPPER"),
        autofill_domain=config.ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN or "invalid.local",
    )


def _auth_service(session: AsyncSession) -> StandaloneAccountAuthService:
    phone_pepper = _secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER")
    return StandaloneAccountAuthService(
        session,
        AccountSessionService(
            session,
            _secret(config.ACCOUNT_AUTH_SESSION_PEPPER, "SESSION_PEPPER"),
        ),
        DeviceRegistrationChallengeService(
            session,
            _secret(config.ACCOUNT_AUTH_INVITATION_PEPPER, "INVITATION_PEPPER"),
            phone_pepper,
        ),
        phone_pepper,
    )


def _device_challenge_service(
    session: AsyncSession,
) -> DeviceRegistrationChallengeService:
    return DeviceRegistrationChallengeService(
        session,
        _secret(config.ACCOUNT_AUTH_INVITATION_PEPPER, "INVITATION_PEPPER"),
        _secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER"),
    )


async def _request_code(
    *,
    phone: str,
    purpose: str,
    account_id: UUID | None,
    session: AsyncSession,
    sender: SmsSender,
) -> SmsRequested:
    try:
        result = await _verification_service(session, sender).request_code(
            RequestPhoneVerificationCode(
                purpose=purpose,
                phone=phone,
                account_id=account_id,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return SmsRequested(
            challenge_id=result.challenge_id,
            expires_at=result.expires_at,
            resend_available_at=result.resend_available_at,
        )
    except SmsDeliveryFailed as error:
        await session.rollback()
        raise _error(503, "sms_temporarily_unavailable") from error
    except PhoneVerificationCooldown as error:
        await session.rollback()
        raise _error(429, "verification_cooldown") from error
    except (InvalidPhoneVerificationRequest, PhoneVerificationUnavailable) as error:
        await session.rollback()
        raise _error(400, "verification_unavailable") from error


async def _verify_code(
    *, body: SmsVerifyRequest, purpose: str, session: AsyncSession
) -> SmsVerified:
    try:
        result = await _verification_service(
            session, UnconfiguredSmsSender()
        ).verify_code(
            VerifyPhoneVerificationCode(
                challenge_id=body.challenge_id,
                phone=body.phone,
                code=body.code,
                now=datetime.now(timezone.utc),
            )
        )
        if isinstance(result, PhoneVerificationRejected):
            await session.commit()
            raise _error(
                423 if result.reason == "locked" else 400,
                "verification_locked"
                if result.reason == "locked"
                else "verification_unavailable",
            )
        if result.purpose != purpose:
            await session.rollback()
            raise _error(400, "verification_unavailable")
        await session.commit()
        return SmsVerified()
    except HTTPException:
        raise
    except (InvalidPhoneVerificationRequest, InvalidOrUnavailablePhoneChallenge) as error:
        await session.rollback()
        raise _error(400, "verification_unavailable") from error


def _decode(value: str, *, urlsafe: bool = False) -> bytes:
    try:
        if urlsafe:
            return base64.b64decode(
                value + "=" * (-len(value) % 4),
                altchars=b"-_",
                validate=True,
            )
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise _error(400, "invalid_request") from error


async def _response_with_token(
    *, result, session: AsyncSession, response: Response
) -> AccountAuthResponse:
    try:
        access = await AccountAccessTokenService(
            session,
            _secret(config.ACCOUNT_AUTH_ACCESS_TOKEN_KEY, "ACCESS_TOKEN_KEY"),
            timedelta(seconds=config.ACCOUNT_AUTH_ACCESS_TOKEN_TTL_SECONDS),
        ).issue(
            IssueAccountAccessToken(
                account_id=result.account_id,
                session_id=result.session_id,
                device_id=result.device_id,
                now=datetime.now(timezone.utc),
            )
        )
    except AccountAccessTokenConfigurationError as error:
        raise _error(503, "configuration_unavailable") from error
    set_web_refresh_cookie(response, result.refresh_token, result.absolute_expires_at)
    return AccountAuthResponse(
        account_id=result.account_id,
        device_id=result.device_id,
        session_id=result.session_id,
        access_token=access.access_token,
        expires_at=access.expires_at,
        display_name=result.display_name,
    )


@router.post(
    "/registration/sms/request",
    response_model=SmsRequested,
    status_code=202,
    responses={400: {"model": PublicError}, 429: {"model": PublicError}, 503: {"model": PublicError}},
)
async def request_registration_sms(
    body: RegistrationSmsRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    sender: Annotated[SmsSender, Depends(get_sms_sender)],
) -> SmsRequested:
    require_web_request(request)
    return await _request_code(
        phone=body.phone,
        purpose="account_registration",
        account_id=None,
        session=session,
        sender=sender,
    )


@router.post(
    "/registration/sms/verify",
    response_model=SmsVerified,
    responses={400: {"model": PublicError}, 423: {"model": PublicError}},
)
async def verify_registration_sms(
    body: SmsVerifyRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> SmsVerified:
    require_web_request(request)
    return await _verify_code(body=body, purpose="account_registration", session=session)


@router.post(
    "/registration/device/challenge",
    response_model=AccountDeviceChallengeResponse,
    responses={400: {"model": PublicError}},
)
async def issue_registration_device_challenge(
    body: AccountDeviceChallengeRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> AccountDeviceChallengeResponse:
    require_web_request(request)
    if body.platform not in _PLATFORMS:
        raise _error(400, "invalid_request")
    try:
        result = await _device_challenge_service(session).issue_account_registration_challenge(
            IssueAccountDeviceRegistrationChallenge(
                phone_verification_challenge_id=body.phone_verification_challenge_id,
                phone=body.phone,
                app_instance_id=body.app_instance_id,
                platform=body.platform,
                public_key=_decode(body.public_key),
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    except DeviceRegistrationChallengeError as error:
        await session.rollback()
        raise _error(400, "registration_unavailable") from error
    return AccountDeviceChallengeResponse(**result.__dict__)


@router.post(
    "/registration/complete",
    response_model=AccountAuthResponse,
    responses={400: {"model": PublicError}, 403: {"model": PublicError}, 503: {"model": PublicError}},
)
async def complete_registration(
    body: StandaloneRegistrationRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> AccountAuthResponse:
    require_web_request(request)
    try:
        result = await _auth_service(session).register(
            RegisterStandaloneAccount(
                phone_verification_challenge_id=body.phone_verification_challenge_id,
                phone=body.phone,
                display_name=body.display_name,
                password=body.password,
                app_instance_id=body.app_instance_id,
                platform=body.platform,
                device_display_name=body.device_display_name,
                device_challenge_id=body.device_challenge_id,
                device_challenge_nonce=_decode(body.device_challenge_nonce, urlsafe=True),
                device_challenge_signature=_decode(body.device_challenge_signature, urlsafe=True),
                now=datetime.now(timezone.utc),
            )
        )
        payload = await _response_with_token(result=result, session=session, response=response)
        await session.commit()
        return payload
    except HTTPException:
        await session.rollback()
        raise
    except (InvalidStandaloneAccountAuthRequest, StandaloneAccountAuthError) as error:
        await session.rollback()
        raise _error(400, "registration_unavailable") from error


@router.post(
    "/login",
    response_model=AccountAuthResponse,
    responses={400: {"model": PublicError}, 401: {"model": PublicError}, 403: {"model": PublicError}, 503: {"model": PublicError}},
)
async def password_login(
    body: PasswordLoginRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> AccountAuthResponse:
    require_web_request(request)
    try:
        result = await _auth_service(session).login(
            LoginStandaloneAccount(
                phone=body.phone,
                password=body.password,
                app_instance_id=body.app_instance_id,
                platform=body.platform,
                device_display_name=body.device_display_name,
                public_key=_decode(body.public_key),
                now=datetime.now(timezone.utc),
            )
        )
        payload = await _response_with_token(result=result, session=session, response=response)
        await session.commit()
        return payload
    except HTTPException:
        await session.rollback()
        raise
    except (InvalidStandaloneAccountAuthRequest, StandaloneAccountAuthError) as error:
        await session.rollback()
        raise _error(401, "authentication_unavailable") from error


@router.post(
    "/password-reset/sms/request",
    response_model=SmsRequested,
    status_code=202,
    responses={400: {"model": PublicError}, 429: {"model": PublicError}, 503: {"model": PublicError}},
)
async def request_password_reset_sms(
    body: PasswordResetRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    sender: Annotated[SmsSender, Depends(get_sms_sender)],
) -> SmsRequested:
    require_web_request(request)
    verification = _verification_service(session, sender)
    account_id = None
    try:
        digest = verification.phone_digest(body.phone)
        identity = (
            await session.execute(
                select(AccountIdentity).where(
                    AccountIdentity.identity_type == "phone",
                    AccountIdentity.provider == "e164",
                    AccountIdentity.subject_digest == digest,
                    AccountIdentity.status == "verified",
                    AccountIdentity.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        account_id = identity.account_id if identity is not None else None
    except InvalidPhoneVerificationRequest:
        pass
    return await _request_code(
        phone=body.phone,
        purpose="password_reset",
        account_id=account_id,
        session=session,
        sender=sender,
    )


@router.post(
    "/password-reset/sms/verify",
    response_model=SmsVerified,
    responses={400: {"model": PublicError}, 423: {"model": PublicError}},
)
async def verify_password_reset_sms(
    body: SmsVerifyRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> SmsVerified:
    require_web_request(request)
    return await _verify_code(body=body, purpose="password_reset", session=session)


@router.post(
    "/password-reset/complete",
    response_model=PasswordResetResponse,
    responses={400: {"model": PublicError}, 403: {"model": PublicError}},
)
async def complete_password_reset(
    body: PasswordResetCompleteRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> PasswordResetResponse:
    require_web_request(request)
    try:
        await _auth_service(session).reset_password(
            ResetStandaloneAccountPassword(
                phone_verification_challenge_id=body.challenge_id,
                phone=body.phone,
                new_password=body.new_password,
                now=datetime.now(timezone.utc),
            )
        )
        clear_web_refresh_cookie(response)
        await session.commit()
        return PasswordResetResponse()
    except (InvalidStandaloneAccountAuthRequest, StandaloneAccountAuthError) as error:
        await session.rollback()
        raise _error(400, "recovery_unavailable") from error
