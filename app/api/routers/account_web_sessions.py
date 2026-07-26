"""Cookie-bound browser sessions and Account bootstrap HTTP boundary."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import (
    account_access_token_service,
    authentication_required,
    get_current_account_principal,
)
from app.api.routers.account_invitation_auth import (
    PublicError,
    _error,
    _web_cookie_config,
    clear_web_refresh_cookie,
    get_account_auth_session,
    require_web_request,
    set_web_refresh_cookie,
)
from app.internal.services.account_access_token_service import (
    AccountAccessTokenConfigurationError,
    AccountAccessTokenRejected,
    CurrentAccountPrincipal,
    InvalidAccountAccessTokenRequest,
    IssueAccountAccessToken,
)
from app.internal.services.account_bootstrap_service import (
    AccountBootstrapService,
    AccountBootstrapUnavailable,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    AccountSessionServiceError,
    RefreshRejected,
    RevokeCurrentRefreshSession,
    RotateRefreshSession,
)
from app.settings import config


router = APIRouter(tags=["account-auth"])


class WebRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class BootstrapAccountResponse(BaseModel):
    id: UUID
    status: str
    security_version: int


class BootstrapCompanyResponse(BaseModel):
    company_id: UUID
    company_name: str
    employee_profile_id: UUID | None
    relationship: str


class AccountBootstrapResponse(BaseModel):
    account: BootstrapAccountResponse
    companies: list[BootstrapCompanyResponse]


def _session_service(session: AsyncSession) -> AccountSessionService:
    pepper = config.ACCOUNT_AUTH_SESSION_PEPPER
    if not isinstance(pepper, str) or len(pepper.encode()) < 32:
        raise _error(503, "configuration_unavailable")
    return AccountSessionService(session, pepper.encode())


def _refresh_cookie(request: Request) -> str:
    name, _secure, _same_site = _web_cookie_config()
    value = request.cookies.get(name)
    if not value:
        raise _error(401, "invalid_or_expired_session")
    return value


def _invalid_refresh_response() -> JSONResponse:
    response = JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": {"code": "invalid_or_expired_session"}},
        headers={"Cache-Control": "private, no-store"},
    )
    clear_web_refresh_cookie(response)
    return response


@router.post(
    "/api/v1/auth/web/sessions/refresh",
    response_model=WebRefreshResponse,
    responses={
        401: {"model": PublicError},
        403: {"model": PublicError},
        503: {"model": PublicError},
    },
)
async def refresh_web_session(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> WebRefreshResponse | Response:
    require_web_request(request)
    token = _refresh_cookie(request)
    now = datetime.now(timezone.utc)
    try:
        rotated = await _session_service(session).rotate_refresh_session(
            RotateRefreshSession(refresh_token=token, now=now)
        )
        if isinstance(rotated, RefreshRejected):
            await session.commit()
            return _invalid_refresh_response()
        access = await account_access_token_service(session).issue(
            IssueAccountAccessToken(
                account_id=rotated.account_id,
                session_id=rotated.session_id,
                device_id=rotated.device_id,
                now=now,
            )
        )
        await session.commit()
    except HTTPException:
        raise
    except AccountAccessTokenConfigurationError as error:
        await session.rollback()
        raise _error(503, "configuration_unavailable") from error
    except (
        AccountSessionServiceError,
        InvalidAccountAccessTokenRequest,
        AccountAccessTokenRejected,
    ):
        await session.rollback()
        return _invalid_refresh_response()
    set_web_refresh_cookie(
        response, rotated.refresh_token, rotated.absolute_expires_at
    )
    return WebRefreshResponse(
        access_token=access.access_token,
        expires_at=access.expires_at,
    )


@router.post(
    "/api/v1/auth/web/sessions/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"model": PublicError},
        503: {"model": PublicError},
    },
)
async def logout_web_session(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> None:
    require_web_request(request)
    name, _secure, _same_site = _web_cookie_config()
    token = request.cookies.get(name)
    try:
        if token:
            await _session_service(session).revoke_current_refresh_session(
                RevokeCurrentRefreshSession(
                    refresh_token=token,
                    now=datetime.now(timezone.utc),
                )
            )
        await session.commit()
    except AccountSessionServiceError:
        await session.rollback()
    clear_web_refresh_cookie(response)


@router.get(
    "/api/v1/account/bootstrap",
    response_model=AccountBootstrapResponse,
    responses={
        401: {"model": PublicError},
        503: {"model": PublicError},
    },
)
async def account_bootstrap(
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> AccountBootstrapResponse:
    try:
        result = await AccountBootstrapService(session).get(
            principal.account_id, datetime.now(timezone.utc)
        )
    except AccountBootstrapUnavailable as error:
        raise authentication_required() from error
    return AccountBootstrapResponse(
        account=BootstrapAccountResponse(
            id=result.account_id,
            status=result.account_status,
            security_version=result.security_version,
        ),
        companies=[
            BootstrapCompanyResponse(**company.__dict__)
            for company in result.companies
        ],
    )
