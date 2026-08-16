"""Owner-only Account API for Venue and employee access management."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
    require_web_request,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.account_organization_access_service import (
    AccountOrganizationAccessService,
    CreateOrganizationVenue,
    OrganizationAccessConflict,
    OrganizationAccessInvalid,
    OrganizationAccessNotFound,
    ReplaceEmployeeAccess,
    ReplaceEmployeePosition,
)


router = APIRouter(
    prefix="/api/v1/account/companies/{company_id}/organization",
    tags=["account-organization"],
)
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrganizationErrorDetail(StrictModel):
    code: Literal[
        "organization_resource_not_found",
        "invalid_organization_request",
        "organization_revision_conflict",
    ]


class OrganizationError(StrictModel):
    detail: OrganizationErrorDetail


class CreateVenueRequest(StrictModel):
    request_id: UUID
    name: str = Field(min_length=1, max_length=255)
    timezone: str | None = Field(default=None, max_length=100)


class VenueResponse(StrictModel):
    created: bool
    venue_id: UUID
    name: str
    code: str
    timezone: str | None
    status: Literal["active", "temporarily_closed", "closed"]


AccessProfileName = Literal[
    "owner",
    "employee_unassigned",
    "employee_venue",
    "venue_manager",
    "organization_manager",
    "unsupported",
]


class EmployeeAccessResponse(StrictModel):
    employee_profile_id: UUID
    display_name: str
    employment_status: Literal["invited", "active", "suspended", "terminated"]
    position_id: UUID
    position_name: str
    profile: AccessProfileName
    venue_ids: list[UUID]
    revision: datetime
    editable: bool


class ReplaceEmployeeAccessRequest(StrictModel):
    profile: Literal[
        "employee_unassigned",
        "employee_venue",
        "venue_manager",
        "organization_manager",
    ]
    venue_ids: list[UUID] = Field(default_factory=list, max_length=100)
    expected_revision: datetime


class ReplaceEmployeePositionRequest(StrictModel):
    position_id: UUID
    expected_revision: datetime


ERRORS = {
    401: {"model": PublicError},
    404: {"model": OrganizationError},
    409: {"model": OrganizationError},
    422: {"model": OrganizationError},
}


def _controlled(error: Exception) -> HTTPException:
    if isinstance(error, OrganizationAccessNotFound):
        code, http = "organization_resource_not_found", status.HTTP_404_NOT_FOUND
    elif isinstance(error, OrganizationAccessInvalid):
        code, http = "invalid_organization_request", status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, OrganizationAccessConflict):
        code, http = "organization_revision_conflict", status.HTTP_409_CONFLICT
    else:
        raise error
    return HTTPException(
        status_code=http,
        detail={"code": code},
        headers={"Cache-Control": NO_STORE},
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = NO_STORE


@router.get("/venues", response_model=list[VenueResponse], responses=ERRORS)
async def list_organization_venues(
    company_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await AccountOrganizationAccessService(session).list_venues(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post("/venues", response_model=VenueResponse, responses=ERRORS)
async def create_organization_venue(
    company_id: UUID,
    body: CreateVenueRequest,
    request: Request,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await AccountOrganizationAccessService(session).create_venue(
            CreateOrganizationVenue(
                actor_account_id=principal.account_id,
                company_id=company_id,
                request_id=body.request_id,
                name=body.name,
                timezone=body.timezone,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get("/employees", response_model=list[EmployeeAccessResponse], responses=ERRORS)
async def list_organization_employees(
    company_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await AccountOrganizationAccessService(session).list_employees(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as error:
        raise _controlled(error) from error


@router.get(
    "/employees/{employee_profile_id}/access",
    response_model=EmployeeAccessResponse,
    responses=ERRORS,
)
async def get_employee_access(
    company_id: UUID,
    employee_profile_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    _no_store(response)
    try:
        return await AccountOrganizationAccessService(session).employee_access(
            principal.account_id,
            company_id,
            employee_profile_id,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.put(
    "/employees/{employee_profile_id}/access",
    response_model=EmployeeAccessResponse,
    responses=ERRORS,
)
async def replace_employee_access(
    company_id: UUID,
    employee_profile_id: UUID,
    body: ReplaceEmployeeAccessRequest,
    request: Request,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await AccountOrganizationAccessService(session).replace_employee_access(
            ReplaceEmployeeAccess(
                actor_account_id=principal.account_id,
                company_id=company_id,
                employee_profile_id=employee_profile_id,
                profile=body.profile,
                venue_ids=tuple(body.venue_ids),
                expected_updated_at=body.expected_revision,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.put(
    "/employees/{employee_profile_id}/position",
    response_model=EmployeeAccessResponse,
    responses=ERRORS,
)
async def replace_employee_position(
    company_id: UUID,
    employee_profile_id: UUID,
    body: ReplaceEmployeePositionRequest,
    request: Request,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await AccountOrganizationAccessService(
            session
        ).replace_employee_position(
            ReplaceEmployeePosition(
                actor_account_id=principal.account_id,
                company_id=company_id,
                employee_profile_id=employee_profile_id,
                position_id=body.position_id,
                expected_updated_at=body.expected_revision,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error
