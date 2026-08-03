"""Browser WebAuthn/passkey HTTP boundary."""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import base64url_to_bytes

from app.api.account_auth import (
    account_access_token_service,
    authentication_required,
    get_current_account_principal,
)
from app.api.routers.account_invitation_auth import (
    PublicError,
    _error,
    get_account_auth_session,
    require_web_request,
    set_web_refresh_cookie,
)
from app.api.routers.account_web_sessions import _session_service
from app.internal.services.account_access_token_service import (
    AccountAccessTokenConfigurationError,
    AccountAccessTokenRejected,
    CurrentAccountPrincipal,
    InvalidAccountAccessTokenRequest,
    IssueAccountAccessToken,
)
from app.internal.services.account_passkey_service import (
    AccountPasskeyRateLimited,
    AccountPasskeyService,
    AccountPasskeyServiceError,
    AccountPasskeyUnavailable,
    AuthenticationVerified,
    InvalidAccountPasskeyRequest,
    PasskeyRejected,
)
from app.settings import config


router = APIRouter(prefix="/api/v1/auth/web/passkeys", tags=["account-auth"])


class DeviceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_instance_id: UUID
    platform: str
    display_name: str | None = Field(default=None, max_length=255)
    public_key: str = Field(min_length=1, max_length=4096)


class PasskeyOptionsResponse(BaseModel):
    challenge_id: UUID
    public_key: dict[str, Any]
    expires_at: datetime


class RegistrationVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    credential: dict[str, Any]
    display_name: str | None = Field(default=None, max_length=255)


class RegistrationVerifyResponse(BaseModel):
    identity_id: UUID
    display_name: str | None


class AuthenticationOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: DeviceContext


class AuthenticationVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    credential: dict[str, Any]
    device: DeviceContext
    device_signature: str = Field(min_length=1, max_length=1024)


class AuthenticationVerifyResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class PasskeyResponse(BaseModel):
    identity_id: UUID
    display_name: str | None
    transports: list[str]
    backup_eligible: bool
    backup_state: bool
    created_at: datetime
    last_used_at: datetime | None
    status: str
    revoked_at: datetime | None


def _service(session: AsyncSession) -> AccountPasskeyService:
    pepper = config.ACCOUNT_AUTH_SESSION_PEPPER
    if not isinstance(pepper, str):
        raise _error(503, "configuration_unavailable")
    try:
        return AccountPasskeyService(
            session,
            rp_id=config.WEBAUTHN_RP_ID,
            rp_name=config.WEBAUTHN_RP_NAME,
            allowed_origins=tuple(config.WEBAUTHN_ALLOWED_ORIGINS),
            session_pepper=pepper.encode("utf-8"),
            challenge_ttl=timedelta(
                seconds=config.WEBAUTHN_CHALLENGE_TTL_SECONDS
            ),
            max_verify_attempts=config.WEBAUTHN_MAX_VERIFY_ATTEMPTS,
        )
    except (TypeError, ValueError) as error:
        raise _error(503, "configuration_unavailable") from error


def _decode(value: str) -> bytes:
    try:
        decoded = base64url_to_bytes(value)
    except Exception as error:
        raise _error(400, "invalid_request") from error
    if not decoded:
        raise _error(400, "invalid_request")
    return decoded


def _authentication_rejected() -> HTTPException:
    return _error(401, "invalid_or_expired_session")


@router.post(
    "/registration/options",
    response_model=PasskeyOptionsResponse,
    responses={401: {"model": PublicError}, 429: {"model": PublicError}},
)
async def registration_options(
    request: Request,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> PasskeyOptionsResponse:
    require_web_request(request)
    try:
        result = await _service(session).begin_registration(
            principal.account_id,
            principal.session_id,
            datetime.now(timezone.utc),
        )
        await session.commit()
    except AccountPasskeyRateLimited as error:
        await session.rollback()
        raise _error(429, "too_many_requests") from error
    except AccountPasskeyServiceError as error:
        await session.rollback()
        raise authentication_required() from error
    return PasskeyOptionsResponse(**result.__dict__)


@router.post(
    "/registration/verify",
    response_model=RegistrationVerifyResponse,
    responses={400: {"model": PublicError}, 401: {"model": PublicError}},
)
async def registration_verify(
    body: RegistrationVerifyRequest,
    request: Request,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> RegistrationVerifyResponse:
    require_web_request(request)
    try:
        result = await _service(session).verify_registration(
            challenge_id=body.challenge_id,
            account_id=principal.account_id,
            session_id=principal.session_id,
            credential=body.credential,
            display_name=body.display_name,
            now=datetime.now(timezone.utc),
        )
        await session.commit()
    except InvalidAccountPasskeyRequest as error:
        await session.rollback()
        raise _error(400, "invalid_request") from error
    except AccountPasskeyServiceError as error:
        await session.rollback()
        raise authentication_required() from error
    if isinstance(result, PasskeyRejected):
        raise _authentication_rejected()
    return RegistrationVerifyResponse(**result.__dict__)


@router.post(
    "/authentication/options",
    response_model=PasskeyOptionsResponse,
    responses={400: {"model": PublicError}, 429: {"model": PublicError}},
)
async def authentication_options(
    body: AuthenticationOptionsRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> PasskeyOptionsResponse:
    require_web_request(request)
    client_host = request.client.host if request.client else "unknown"
    try:
        result = await _service(session).begin_authentication(
            app_instance_id=body.device.app_instance_id,
            platform=body.device.platform,
            display_name=body.device.display_name,
            public_key=_decode(body.device.public_key),
            rate_limit_subject=client_host.encode("utf-8"),
            now=datetime.now(timezone.utc),
        )
        await session.commit()
    except AccountPasskeyRateLimited as error:
        await session.rollback()
        raise _error(429, "too_many_requests") from error
    except InvalidAccountPasskeyRequest as error:
        await session.rollback()
        raise _error(400, "invalid_request") from error
    return PasskeyOptionsResponse(**result.__dict__)


@router.post(
    "/authentication/verify",
    response_model=AuthenticationVerifyResponse,
    responses={400: {"model": PublicError}, 401: {"model": PublicError}},
)
async def authentication_verify(
    body: AuthenticationVerifyRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> AuthenticationVerifyResponse:
    require_web_request(request)
    now = datetime.now(timezone.utc)
    try:
        result = await _service(session).verify_authentication(
            challenge_id=body.challenge_id,
            credential=body.credential,
            app_instance_id=body.device.app_instance_id,
            platform=body.device.platform,
            display_name=body.device.display_name,
            public_key=_decode(body.device.public_key),
            device_signature=_decode(body.device_signature),
            session_service=_session_service(session),
            now=now,
        )
        if isinstance(result, PasskeyRejected):
            await session.commit()
            raise _authentication_rejected()
        assert isinstance(result, AuthenticationVerified)
        issued = await account_access_token_service(session).issue(
            IssueAccountAccessToken(
                account_id=result.account_id,
                session_id=result.device_session.session_id,
                device_id=result.device_session.device_id,
                now=now,
            )
        )
        await session.commit()
    except HTTPException:
        raise
    except InvalidAccountPasskeyRequest as error:
        await session.rollback()
        raise _error(400, "invalid_request") from error
    except AccountAccessTokenConfigurationError as error:
        await session.rollback()
        raise _error(503, "configuration_unavailable") from error
    except (
        AccountPasskeyServiceError,
        InvalidAccountAccessTokenRequest,
        AccountAccessTokenRejected,
    ) as error:
        await session.rollback()
        raise _authentication_rejected() from error
    set_web_refresh_cookie(
        response,
        result.device_session.refresh_token,
        result.device_session.absolute_expires_at,
    )
    return AuthenticationVerifyResponse(
        access_token=issued.access_token,
        expires_at=issued.expires_at,
    )


@router.get(
    "",
    response_model=list[PasskeyResponse],
    responses={401: {"model": PublicError}},
)
async def list_passkeys(
    request: Request,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[PasskeyResponse]:
    require_web_request(request)
    try:
        result = await _service(session).list_passkeys(
            principal.account_id, datetime.now(timezone.utc)
        )
    except AccountPasskeyServiceError as error:
        raise authentication_required() from error
    return [
        PasskeyResponse(
            identity_id=item.identity_id,
            display_name=item.display_name,
            transports=list(item.transports),
            backup_eligible=item.backup_eligible,
            backup_state=item.backup_state,
            created_at=item.created_at,
            last_used_at=item.last_used_at,
            status=item.status,
            revoked_at=item.revoked_at,
        )
        for item in result
    ]


@router.delete(
    "/{identity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: {"model": PublicError}, 404: {"model": PublicError}},
)
async def revoke_passkey(
    identity_id: UUID,
    request: Request,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> None:
    require_web_request(request)
    try:
        await _service(session).revoke_passkey(
            principal.account_id, identity_id, datetime.now(timezone.utc)
        )
        await session.commit()
    except AccountPasskeyUnavailable as error:
        await session.rollback()
        raise _error(404, "passkey_not_found") from error
    except AccountPasskeyServiceError as error:
        await session.rollback()
        raise authentication_required() from error
