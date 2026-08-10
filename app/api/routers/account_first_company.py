"""Authenticated HTTP boundary for the first Owner/Company aggregate."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
    require_web_request,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.first_company_service import (
    CreateFirstCompany,
    FirstCompanyError,
    FirstCompanyService,
    FirstCompanyUnavailable,
    InvalidFirstCompanyRequest,
)


router = APIRouter(prefix="/api/v1/account", tags=["account-onboarding"])
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateFirstCompanyRequest(StrictModel):
    company_name: str = Field(min_length=1, max_length=255)
    venue_name: str | None = Field(default=None, max_length=255)
    timezone: str = Field(default="Europe/Moscow", min_length=1, max_length=100)
    locale: str = Field(default="ru-RU", min_length=2, max_length=35)


class FirstCompanyResponse(StrictModel):
    created: bool
    company_id: UUID
    company_name: str
    company_code: str
    employee_profile_id: UUID
    position_id: UUID
    access_profile_id: UUID
    employee_assignment_id: UUID
    venue_id: UUID | None
    relationship: Literal["owner"] = "owner"


def _safe_error(code: str, http_status: int) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"code": code},
        headers={"Cache-Control": NO_STORE},
    )


@router.post(
    "/companies/first",
    response_model=FirstCompanyResponse,
    responses={
        401: {"model": PublicError},
        403: {"model": PublicError},
        409: {"model": PublicError},
        422: {"model": PublicError},
    },
)
async def create_first_company(
    body: CreateFirstCompanyRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> FirstCompanyResponse:
    require_web_request(request)
    response.headers["Cache-Control"] = NO_STORE
    try:
        result = await FirstCompanyService(session).create(
            CreateFirstCompany(
                account_id=principal.account_id,
                expected_security_version=principal.security_version,
                company_name=body.company_name,
                venue_name=body.venue_name,
                timezone=body.timezone,
                locale=body.locale,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    except InvalidFirstCompanyRequest as error:
        await session.rollback()
        raise _safe_error("invalid_company_request", status.HTTP_422_UNPROCESSABLE_ENTITY) from error
    except FirstCompanyUnavailable as error:
        await session.rollback()
        raise _safe_error("company_onboarding_unavailable", status.HTTP_409_CONFLICT) from error
    except IntegrityError as error:
        await session.rollback()
        raise _safe_error("company_onboarding_unavailable", status.HTTP_409_CONFLICT) from error
    except FirstCompanyError as error:
        await session.rollback()
        raise _safe_error("company_onboarding_unavailable", status.HTTP_409_CONFLICT) from error
    return FirstCompanyResponse(
        created=result.created,
        company_id=result.company_id,
        company_name=result.company_name,
        company_code=result.company_code,
        employee_profile_id=result.employee_profile_id,
        position_id=result.position_id,
        access_profile_id=result.access_profile_id,
        employee_assignment_id=result.employee_assignment_id,
        venue_id=result.venue_id,
    )
