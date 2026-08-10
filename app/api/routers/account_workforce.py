"""Account-only workforce onboarding boundary."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    _secret,
    get_account_auth_session,
    require_web_request,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.account_workforce_onboarding_service import (
    AccountWorkforceOnboardingConflict,
    AccountWorkforceOnboardingForbidden,
    AccountWorkforceOnboardingInvalid,
    AccountWorkforceOnboardingService,
    CreateAccountWorkforceInvitation,
)
from app.settings import config


router = APIRouter(
    prefix="/api/v1/account/companies/{company_id}/workforce",
    tags=["account-workforce"],
)
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkforceErrorDetail(StrictModel):
    code: Literal[
        "permission_denied",
        "invalid_workforce_invitation",
        "workforce_invitation_conflict",
    ]


class WorkforceError(StrictModel):
    detail: WorkforceErrorDetail


class WorkforceVenueResponse(StrictModel):
    venue_id: UUID
    name: str


class CreateWorkforceInvitationRequest(StrictModel):
    request_id: UUID
    employee_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=50)
    venue_id: UUID | None = None


class WorkforceInvitationResponse(StrictModel):
    created: bool
    invitation_id: UUID
    employee_profile_id: UUID
    invitation_code: str = Field(pattern=r"^[0-9]{6}$")
    expires_at: datetime


ERRORS = {
    401: {"model": PublicError},
    403: {"model": WorkforceError},
    409: {"model": WorkforceError},
    422: {"model": WorkforceError},
}


def _service(session: AsyncSession) -> AccountWorkforceOnboardingService:
    return AccountWorkforceOnboardingService(
        session,
        _secret(config.ACCOUNT_AUTH_INVITATION_PEPPER, "INVITATION_PEPPER"),
        _secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER"),
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = NO_STORE


def _controlled(error: Exception) -> HTTPException:
    if isinstance(error, AccountWorkforceOnboardingForbidden):
        code, http_status = "permission_denied", status.HTTP_403_FORBIDDEN
    elif isinstance(error, AccountWorkforceOnboardingInvalid):
        code, http_status = (
            "invalid_workforce_invitation",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    elif isinstance(error, AccountWorkforceOnboardingConflict):
        code, http_status = (
            "workforce_invitation_conflict",
            status.HTTP_409_CONFLICT,
        )
    else:
        raise error
    return HTTPException(
        status_code=http_status,
        detail={"code": code},
        headers={"Cache-Control": NO_STORE},
    )


@router.get(
    "/venues",
    response_model=list[WorkforceVenueResponse],
    responses=ERRORS,
)
async def list_workforce_venues(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).list_venues(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/invitations",
    response_model=WorkforceInvitationResponse,
    responses=ERRORS,
)
async def create_workforce_invitation(
    company_id: UUID,
    body: CreateWorkforceInvitationRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> WorkforceInvitationResponse:
    require_web_request(request)
    _no_store(response)
    try:
        result = await _service(session).create_invitation(
            CreateAccountWorkforceInvitation(
                actor_account_id=principal.account_id,
                company_id=company_id,
                request_id=body.request_id,
                employee_name=body.employee_name,
                phone=body.phone,
                venue_id=body.venue_id,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    except Exception as error:
        await session.rollback()
        try:
            controlled = _controlled(error)
        except Exception:
            raise
        raise controlled from error
    return WorkforceInvitationResponse(
        created=result.created,
        invitation_id=result.invitation_id,
        employee_profile_id=result.employee_profile_id,
        invitation_code=result.code,
        expires_at=result.expires_at,
    )
