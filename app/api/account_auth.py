"""Reusable FastAPI dependency for additive Account bearer authentication."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routers.account_invitation_auth import get_account_auth_session
from app.internal.services.account_access_token_service import (
    AccountAccessTokenConfigurationError,
    AccountAccessTokenRejected,
    AccountAccessTokenService,
    CurrentAccountPrincipal,
    InvalidAccountAccessTokenRequest,
    VerifyAccountAccessToken,
)
from app.settings import config


_bearer = HTTPBearer(auto_error=False)


def account_access_token_service(session: AsyncSession) -> AccountAccessTokenService:
    key = config.ACCOUNT_AUTH_ACCESS_TOKEN_KEY
    if not isinstance(key, str):
        raise AccountAccessTokenConfigurationError(
            "account access-token configuration is unavailable"
        )
    return AccountAccessTokenService(
        session,
        key.encode("utf-8"),
        timedelta(seconds=config.ACCOUNT_AUTH_ACCESS_TOKEN_TTL_SECONDS),
    )


def authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required"},
        headers={
            "WWW-Authenticate": "Bearer",
            "Cache-Control": "no-store",
        },
    )


async def get_current_account_principal(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> CurrentAccountPrincipal:
    del request
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_required()
    try:
        return await account_access_token_service(session).verify(
            VerifyAccountAccessToken(
                access_token=credentials.credentials,
                now=datetime.now(timezone.utc),
            )
        )
    except AccountAccessTokenConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "configuration_unavailable"},
            headers={"Cache-Control": "no-store"},
        ) from error
    except (
        InvalidAccountAccessTokenRequest,
        AccountAccessTokenRejected,
    ) as error:
        raise authentication_required() from error
