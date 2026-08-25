"""Authenticated, phone-bound workforce invitation acceptance."""

from datetime import datetime, timezone
from typing import Annotated, Literal

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
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.workforce_invitation_service import (
    AcceptAuthenticatedWorkforceInvitation,
    AccountAlreadyMemberOfCompany,
    WorkforceInvitationError,
    WorkforceInvitationService,
)
from app.settings import config


router = APIRouter(
    prefix="/api/v1/account/workforce/invitations",
    tags=["account-workforce"],
)
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AcceptInvitationRequest(StrictModel):
    invitation_code: str = Field(pattern=r"^[0-9]{6}$")


class AcceptInvitationResponse(StrictModel):
    joined: Literal[True]
    company_name: str
    position_name: str
    venue_names: tuple[str, ...]


class InvitationJoinErrorDetail(StrictModel):
    code: Literal["invitation_unavailable", "invitation_conflict"]


class InvitationJoinError(StrictModel):
    detail: InvitationJoinErrorDetail


RESPONSES = {
    400: {"model": InvitationJoinError},
    401: {"model": PublicError},
    409: {"model": InvitationJoinError},
}


@router.post(
    "/accept",
    response_model=AcceptInvitationResponse,
    responses=RESPONSES,
)
async def accept_existing_account_invitation(
    body: AcceptInvitationRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> AcceptInvitationResponse:
    require_web_request(request)
    response.headers["Cache-Control"] = NO_STORE
    service = WorkforceInvitationService(
        session,
        AccessDecisionService(session),
        _secret(config.ACCOUNT_AUTH_INVITATION_PEPPER, "INVITATION_PEPPER"),
    )
    try:
        accepted = await service.accept_authenticated(
            AcceptAuthenticatedWorkforceInvitation(
                account_id=principal.account_id,
                code=body.invitation_code,
                now=datetime.now(timezone.utc),
            ),
            _secret(config.ACCOUNT_AUTH_PHONE_PEPPER, "PHONE_PEPPER"),
        )
        projection = await service.acceptance_projection(accepted)
        await session.commit()
    except AccountAlreadyMemberOfCompany as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invitation_conflict"},
            headers={"Cache-Control": NO_STORE},
        ) from error
    except WorkforceInvitationError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invitation_unavailable"},
            headers={"Cache-Control": NO_STORE},
        ) from error
    except Exception:
        await session.rollback()
        raise
    return AcceptInvitationResponse(
        joined=True,
        company_name=projection.company_name,
        position_name=projection.position_name,
        venue_names=projection.venue_names,
    )
