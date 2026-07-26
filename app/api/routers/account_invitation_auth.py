"""HTTP boundary for additive invited-employee Account registration."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import hmac
import re
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.infra.database.models.invitation_v1 import Invitation
from app.infra.sms import SmsAeroSender
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.account_session_service import AccountSessionService
from app.internal.services.device_registration_challenge_service import (
    DeviceRegistrationChallengeError,
    DeviceRegistrationChallengeService,
    InvalidDeviceRegistrationChallengeRequest,
    IssueDeviceRegistrationChallenge,
)
from app.internal.services.invited_employee_registration_service import (
    InvalidInvitedEmployeeRegistration,
    InvitedEmployeeRegistrationError,
    InvitedEmployeeRegistrationService,
    RegisterInvitedEmployee,
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
from app.internal.services.workforce_invitation_service import (
    WorkforceInvitationService,
)
from app.settings import config


AUTH_PREFIX = "/api/v1/auth/invitations"
router = APIRouter(prefix=AUTH_PREFIX, tags=["account-auth"])
_SIX_ASCII_DIGITS = re.compile(r"^[0-9]{6}$")
_PLATFORMS = {"ios", "android", "web", "desktop", "unknown"}
_engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


class SmsSender(Protocol):
    async def send_verification_code(
        self,
        phone: str,
        code: str,
        purpose: str,
        expires_in_seconds: int,
        autofill_domain: str,
    ) -> None: ...


class SmsProviderUnavailable(RuntimeError):
    """No production SMS adapter is configured."""


class UnconfiguredSmsSender:
    async def send_verification_code(self, **_: object) -> None:
        raise SmsProviderUnavailable("SMS provider is not configured")


class PublicError(BaseModel):
    code: str


class SmsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
    phone: str = Field(min_length=8, max_length=32)


class SmsRequested(BaseModel):
    challenge_id: UUID
    expires_at: datetime
    resend_available_at: datetime


class SmsVerify(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    phone: str = Field(min_length=8, max_length=32)
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
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


class DeviceChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation_code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
    phone_verification_challenge_id: UUID
    phone: str = Field(min_length=8, max_length=32)
    app_instance_id: UUID
    platform: str
    public_key: str = Field(min_length=4, max_length=8192)


class DeviceChallengeResponse(BaseModel):
    device_challenge_id: UUID
    nonce: str
    algorithm: str
    expires_at: datetime


class RegistrationResponse(BaseModel):
    account_id: UUID
    employee_profile_id: UUID
    employee_assignment_id: UUID
    company_id: UUID
    device_id: UUID
    session_id: UUID
    refresh_token: str
    display_name: str


async def get_account_auth_session():
    async with _session_factory() as session:
        yield session


def get_sms_sender(request: Request) -> SmsSender:
    provider = config.SMS_PROVIDER.strip().lower()
    if provider in {"", "disabled"}:
        return UnconfiguredSmsSender()
    if provider != "smsaero":
        raise _error(503, "sms_temporarily_unavailable")
    values = (
        config.SMS_AERO_EMAIL,
        config.SMS_AERO_API_KEY,
        config.SMS_AERO_SIGN,
        config.SMS_AERO_BASE_URL,
    )
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise _error(503, "sms_temporarily_unavailable")
    client = getattr(request.app.state, "sms_http_client", None)
    if client is None:
        raise _error(503, "sms_temporarily_unavailable")
    try:
        return SmsAeroSender(
            client,
            email=config.SMS_AERO_EMAIL,
            api_key=config.SMS_AERO_API_KEY,
            sign=config.SMS_AERO_SIGN,
            base_url=config.SMS_AERO_BASE_URL,
            timeout_seconds=config.SMS_HTTP_TIMEOUT_SECONDS,
        )
    except ValueError as error:
        raise _error(503, "sms_temporarily_unavailable") from error


def _secret(value: str, name: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "sms_temporarily_unavailable" if "SMS" in name else "registration_unavailable"},
        )
    return raw


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _error(http_status: int, code: str) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"code": code},
        headers={"Cache-Control": "no-store"},
    )


def configure_account_auth_http_security(app: FastAPI) -> None:
    """Install path-scoped cache and validation protection on the existing app."""

    @app.middleware("http")
    async def account_auth_no_store(request: Request, call_next):
        if not request.url.path.startswith(AUTH_PREFIX):
            return await call_next(request)
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse(
                status_code=500,
                content={"detail": {"code": "internal_error"}},
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def account_auth_validation_error(
        request: Request, exc: RequestValidationError
    ):
        if not request.url.path.startswith(AUTH_PREFIX):
            return await request_validation_exception_handler(request, exc)
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "invalid_request"}},
            headers={"Cache-Control": "no-store"},
        )


@router.post(
    "/sms/request",
    response_model=SmsRequested,
    status_code=status.HTTP_202_ACCEPTED,
    responses={503: {"model": PublicError}},
)
async def request_sms(
    body: SmsRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    sender: Annotated[SmsSender, Depends(get_sms_sender)],
) -> SmsRequested:
    _no_store(response)
    now = datetime.now(timezone.utc)
    invitation_pepper = _secret(
        config.ACCOUNT_AUTH_INVITATION_PEPPER, "INVITATION_PEPPER"
    )
    digest = hmac.new(
        invitation_pepper, body.invitation_code.encode("ascii"), hashlib.sha256
    ).digest()
    invitation = (
        await session.execute(
            select(Invitation).where(
                Invitation.code_digest == digest,
                Invitation.status == "pending",
                Invitation.deleted_at.is_(None),
                Invitation.expires_at > now,
            )
        )
    ).scalar_one_or_none()
    if invitation is None:
        return SmsRequested(
            challenge_id=uuid4(),
            expires_at=now,
            resend_available_at=now,
        )
    service = PhoneVerificationService(
        session=session,
        sender=sender,
        phone_pepper=_secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER"),
        code_pepper=_secret(config.ACCOUNT_AUTH_CODE_PEPPER, "CODE_PEPPER"),
        autofill_domain=config.ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN or "invalid.local",
    )
    try:
        result = await service.request_code(
            RequestPhoneVerificationCode(
                purpose="invitation_registration",
                phone=body.phone,
                now=now,
                invitation_id=invitation.id,
                employee_profile_id=invitation.employee_profile_id,
            )
        )
        await session.commit()
    except SmsDeliveryFailed as error:
        await session.rollback()
        raise _error(503, "sms_temporarily_unavailable") from error
    except PhoneVerificationCooldown as error:
        await session.rollback()
        raise _error(429, "verification_cooldown") from error
    except (InvalidPhoneVerificationRequest, PhoneVerificationUnavailable) as error:
        await session.rollback()
        raise _error(400, "verification_unavailable") from error
    return SmsRequested(
        challenge_id=result.challenge_id,
        expires_at=result.expires_at,
        resend_available_at=result.resend_available_at,
    )


@router.post(
    "/sms/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={400: {"model": PublicError}, 423: {"model": PublicError}},
)
async def verify_sms(
    body: SmsVerify,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> None:
    _no_store(response)
    service = PhoneVerificationService(
        session=session,
        sender=UnconfiguredSmsSender(),
        phone_pepper=_secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER"),
        code_pepper=_secret(config.ACCOUNT_AUTH_CODE_PEPPER, "CODE_PEPPER"),
        autofill_domain=config.ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN or "invalid.local",
    )
    try:
        result = await service.verify_code(
            VerifyPhoneVerificationCode(
                challenge_id=body.challenge_id,
                phone=body.phone,
                code=body.code,
                now=datetime.now(timezone.utc),
            )
        )
        if isinstance(result, PhoneVerificationRejected):
            await session.commit()
            code = "verification_locked" if result.reason == "locked" else "verification_unavailable"
            raise _error(423 if result.reason == "locked" else 400, code)
        await session.commit()
    except HTTPException:
        raise
    except (InvalidPhoneVerificationRequest, InvalidOrUnavailablePhoneChallenge) as error:
        await session.rollback()
        raise _error(400, "verification_unavailable") from error


@router.post(
    "/device/challenge",
    response_model=DeviceChallengeResponse,
    responses={400: {"model": PublicError}},
)
async def issue_device_challenge(
    body: DeviceChallengeRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> DeviceChallengeResponse:
    _no_store(response)
    if body.platform not in _PLATFORMS:
        raise _error(400, "invalid_request")
    try:
        public_key = base64.b64decode(body.public_key, validate=True)
    except (ValueError, binascii.Error) as error:
        raise _error(400, "registration_unavailable") from error
    service = DeviceRegistrationChallengeService(
        session,
        _secret(config.ACCOUNT_AUTH_INVITATION_PEPPER, "INVITATION_PEPPER"),
        _secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER"),
    )
    try:
        result = await service.issue_challenge(
            IssueDeviceRegistrationChallenge(
                invitation_code=body.invitation_code,
                phone_verification_challenge_id=body.phone_verification_challenge_id,
                phone=body.phone,
                app_instance_id=body.app_instance_id,
                platform=body.platform,
                public_key=public_key,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    except (
        InvalidDeviceRegistrationChallengeRequest,
        DeviceRegistrationChallengeError,
    ) as error:
        await session.rollback()
        raise _error(400, "registration_unavailable") from error
    return DeviceChallengeResponse(**result.__dict__)


@router.post(
    "/register",
    response_model=RegistrationResponse,
    responses={400: {"model": PublicError}},
)
async def register(
    body: RegistrationRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> RegistrationResponse:
    _no_store(response)
    if body.platform not in _PLATFORMS:
        raise _error(400, "invalid_request")
    try:
        nonce = base64.b64decode(
            body.device_challenge_nonce + "=",
            altchars=b"-_",
            validate=True,
        )
        signature = base64.b64decode(
            body.device_challenge_signature
            + "=" * (-len(body.device_challenge_signature) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as error:
        raise _error(400, "invalid_request") from error
    invitation_pepper = _secret(
        config.ACCOUNT_AUTH_INVITATION_PEPPER, "INVITATION_PEPPER"
    )
    phone_pepper = _secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER")
    workforce = WorkforceInvitationService(
        session,
        AccessDecisionService(session),
        invitation_pepper,
    )
    account_sessions = AccountSessionService(
        session,
        _secret(config.ACCOUNT_AUTH_SESSION_PEPPER, "SESSION_PEPPER"),
    )
    device_challenges = DeviceRegistrationChallengeService(
        session, invitation_pepper, phone_pepper
    )
    service = InvitedEmployeeRegistrationService(
        session,
        workforce,
        account_sessions,
        device_challenges,
        invitation_pepper,
        phone_pepper,
    )
    try:
        result = await service.register(
            RegisterInvitedEmployee(
                invitation_code=body.invitation_code,
                phone_verification_challenge_id=body.phone_verification_challenge_id,
                phone=body.phone,
                display_name=body.display_name,
                password=body.password,
                app_instance_id=body.app_instance_id,
                platform=body.platform,
                device_display_name=body.device_display_name,
                device_challenge_id=body.device_challenge_id,
                device_challenge_nonce=nonce,
                device_challenge_signature=signature,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    except (InvalidInvitedEmployeeRegistration, InvitedEmployeeRegistrationError) as error:
        await session.rollback()
        raise _error(400, "registration_unavailable") from error
    return RegistrationResponse(**result.__dict__)
