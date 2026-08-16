"""Strict Account-scoped operational walkthrough boundary."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_assessments import AttemptDocumentResponse
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.assessment_operational_walkthrough_service import (
    AssessmentOperationalWalkthroughService,
    OperationalWalkthroughConflict,
    OperationalWalkthroughNotFound,
    OperationalWalkthroughPermissionDenied,
)


router = APIRouter(
    prefix="/api/v1/account/companies/{company_id}/operational-walkthroughs",
    tags=["account-operational-walkthroughs"],
)
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OperationalWalkthroughTemplateResponse(StrictModel):
    template_id: UUID
    template_version_id: UUID
    name: str
    version: int = Field(ge=1)
    section_count: int = Field(ge=1)
    item_count: int = Field(ge=1)
    scoring_algorithm: Literal["weighted_v1"]
    scoring_ready: Literal[True]


class StartOperationalWalkthroughRequest(StrictModel):
    venue_id: UUID
    template_version_id: UUID


class OperationalWalkthroughErrorDetail(StrictModel):
    code: Literal[
        "permission_denied",
        "operational_walkthrough_not_found",
        "operational_walkthrough_conflict",
    ]


class OperationalWalkthroughError(StrictModel):
    detail: OperationalWalkthroughErrorDetail


ERRORS = {
    401: {"model": PublicError},
    403: {"model": OperationalWalkthroughError},
    404: {"model": OperationalWalkthroughError},
    409: {"model": OperationalWalkthroughError},
}


def _error(problem: Exception) -> HTTPException:
    if isinstance(problem, OperationalWalkthroughPermissionDenied):
        code, http = "permission_denied", status.HTTP_403_FORBIDDEN
    elif isinstance(problem, OperationalWalkthroughNotFound):
        code, http = (
            "operational_walkthrough_not_found",
            status.HTTP_404_NOT_FOUND,
        )
    elif isinstance(problem, OperationalWalkthroughConflict):
        code, http = (
            "operational_walkthrough_conflict",
            status.HTTP_409_CONFLICT,
        )
    else:
        raise problem
    return HTTPException(
        status_code=http,
        detail={"code": code},
        headers={"Cache-Control": NO_STORE},
    )


@router.get(
    "/templates",
    response_model=list[OperationalWalkthroughTemplateResponse],
    responses=ERRORS,
)
async def list_operational_walkthrough_templates(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        return await AssessmentOperationalWalkthroughService(session).list_templates(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as problem:
        raise _error(problem) from problem


@router.post(
    "",
    response_model=AttemptDocumentResponse,
    status_code=201,
    responses=ERRORS,
)
async def start_operational_walkthrough(
    company_id: UUID,
    request: StartOperationalWalkthroughRequest,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    response.headers["Cache-Control"] = NO_STORE
    try:
        return await AssessmentOperationalWalkthroughService(session).start(
            principal.account_id,
            company_id,
            request.venue_id,
            request.template_version_id,
            datetime.now(timezone.utc),
        )
    except Exception as problem:
        raise _error(problem) from problem
