"""HTTP refresh boundary for additive Account sessions."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import account_access_token_service, authentication_required
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import (
    AccountAccessTokenConfigurationError,
    AccountAccessTokenRejected,
    IssueAccountAccessToken,
    InvalidAccountAccessTokenRequest,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    AccountSessionServiceError,
    RefreshRejected,
    RotateRefreshSession,
)
from app.settings import config


AUTH_SESSION_PREFIX = "/api/v1/auth/sessions"
router = APIRouter(prefix=AUTH_SESSION_PREFIX, tags=["account-auth"])


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1, max_length=2048)


class RefreshResponse(BaseModel):
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_session_id: UUID
    refresh_idle_expires_at: datetime
    refresh_absolute_expires_at: datetime
    token_type: str = "bearer"


def _session_pepper() -> bytes:
    value = config.ACCOUNT_AUTH_SESSION_PEPPER
    if not isinstance(value, str) or len(value.encode("utf-8")) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "configuration_unavailable"},
            headers={"Cache-Control": "no-store"},
        )
    return value.encode("utf-8")


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    responses={
        401: {"model": PublicError},
        503: {"model": PublicError},
    },
)
async def refresh(
    body: RefreshRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> RefreshResponse:
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    try:
        rotated = await AccountSessionService(
            session, _session_pepper()
        ).rotate_refresh_session(
            RotateRefreshSession(refresh_token=body.refresh_token, now=now)
        )
        if isinstance(rotated, RefreshRejected):
            await session.commit()
            raise authentication_required()
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "configuration_unavailable"},
            headers={"Cache-Control": "no-store"},
        ) from error
    except (
        AccountSessionServiceError,
        InvalidAccountAccessTokenRequest,
        AccountAccessTokenRejected,
    ) as error:
        await session.rollback()
        raise authentication_required() from error
    return RefreshResponse(
        access_token=access.access_token,
        access_token_expires_at=access.expires_at,
        refresh_token=rotated.refresh_token,
        refresh_session_id=rotated.session_id,
        refresh_idle_expires_at=rotated.idle_expires_at,
        refresh_absolute_expires_at=rotated.absolute_expires_at,
    )
