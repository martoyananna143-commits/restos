"""Account-scoped manager boundary for assessment assignments."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
)
from app.internal.services.account_access_token_service import (
    CurrentAccountPrincipal,
)
from app.internal.services.assessment_management_service import (
    AssessmentManagementAlreadyCompleted,
    AssessmentManagementDuplicate,
    AssessmentManagementInvalid,
    AssessmentManagementNotFound,
    AssessmentManagementPermissionDenied,
    AssessmentManagementService,
    AssessmentManagementStateConflict,
    CreateAssignment,
    StartManagerMeasurement,
)
from app.api.routers.account_assessments import AttemptDocumentResponse


router = APIRouter(
    prefix="/api/v1/account/companies/{company_id}/assessment-management",
    tags=["account-assessment-management"],
)
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManagementErrorDetail(StrictModel):
    code: Literal[
        "permission_denied",
        "assessment_management_not_found",
        "duplicate_active_assignment",
        "assessment_already_completed",
        "assessment_state_conflict",
        "invalid_assessment_assignment",
    ]


class ManagementError(StrictModel):
    detail: ManagementErrorDetail


class EmployeeSummary(StrictModel):
    employee_profile_id: UUID
    display_name: str
    position_title: str | None
    status: Literal["active"]
    venue_ids: list[UUID] | None = None
    venue_required: bool | None = None


class TemplateVersionSummary(StrictModel):
    template_id: UUID
    template_version_id: UUID
    name: str
    activity_type: Literal[
        "evaluation",
        "measurement",
        "walkthrough",
        "checklist",
        "test",
        "survey",
        "attestation",
    ]
    version: int = Field(ge=1)
    published_at: datetime


class AssignmentEmployee(StrictModel):
    employee_profile_id: UUID
    display_name: str
    position_title: str | None


class AssignmentTemplate(StrictModel):
    template_id: UUID
    template_version_id: UUID
    name: str
    version: int = Field(ge=1)


class CompletionReceipt(StrictModel):
    scoring_algorithm: Literal["completion_v1", "weighted_v1"]
    submitted_at: datetime
    answered_count: int = Field(ge=0)
    required_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    scoring_version: int | None = Field(default=None, ge=1)
    score_percent: str | None = None
    coverage: str | None = None
    critical_failure_count: int | None = Field(default=None, ge=0)
    stop_factor_count: int | None = Field(default=None, ge=0)


class AssignmentProgress(StrictModel):
    answered_count: int = Field(ge=0)
    required_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    started_at: datetime | None
    last_saved_at: datetime | None
    submitted_at: datetime | None
    completion: CompletionReceipt | None


class ManagerAssignmentResponse(StrictModel):
    id: UUID
    venue_id: UUID | None
    status: Literal["assigned", "in_progress", "completed", "revoked"]
    assigned_at: datetime
    due_at: datetime | None
    revoked_at: datetime | None
    completed_at: datetime | None
    employee: AssignmentEmployee
    template: AssignmentTemplate
    progress: AssignmentProgress


class CreateAssignmentRequest(StrictModel):
    employee_profile_id: UUID
    template_version_id: UUID
    venue_id: UUID | None = None
    due_at: datetime | None = None

    @field_validator("due_at")
    @classmethod
    def due_at_is_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must be timezone-aware")
        return value


class StartManagerMeasurementRequest(StrictModel):
    employee_profile_id: UUID
    template_version_id: UUID
    venue_id: UUID | None = None


ERRORS = {
    401: {"model": PublicError},
    403: {"model": ManagementError},
    404: {"model": ManagementError},
    409: {"model": ManagementError},
    422: {"model": ManagementError},
}


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = NO_STORE


def _controlled(error: Exception) -> HTTPException:
    if isinstance(error, AssessmentManagementPermissionDenied):
        code, http_status = "permission_denied", status.HTTP_403_FORBIDDEN
    elif isinstance(error, AssessmentManagementNotFound):
        code, http_status = (
            "assessment_management_not_found",
            status.HTTP_404_NOT_FOUND,
        )
    elif isinstance(error, AssessmentManagementDuplicate):
        code, http_status = (
            "duplicate_active_assignment",
            status.HTTP_409_CONFLICT,
        )
    elif isinstance(error, AssessmentManagementAlreadyCompleted):
        code, http_status = (
            "assessment_already_completed",
            status.HTTP_409_CONFLICT,
        )
    elif isinstance(error, AssessmentManagementStateConflict):
        code, http_status = (
            "assessment_state_conflict",
            status.HTTP_409_CONFLICT,
        )
    elif isinstance(error, AssessmentManagementInvalid):
        code, http_status = (
            "invalid_assessment_assignment",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    else:
        raise error
    return HTTPException(
        status_code=http_status,
        detail={"code": code},
        headers={"Cache-Control": NO_STORE},
    )


@router.get(
    "/employees",
    response_model=list[EmployeeSummary],
    response_model_exclude_none=True,
    responses=ERRORS,
)
async def list_management_employees(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: UUID | None = None,
    include_venue_ids: bool = False,
) -> list[dict[str, Any]]:
    _no_store(response)
    try:
        return await AssessmentManagementService(session).list_employees(
            principal.account_id,
            company_id,
            datetime.now(timezone.utc),
            q=q,
            limit=limit,
            after=after,
            include_venue_ids=include_venue_ids,
        )
    except Exception as error:
        raise _controlled(error) from error


@router.get("/templates", response_model=list[TemplateVersionSummary], responses=ERRORS)
async def list_management_templates(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, Any]]:
    _no_store(response)
    try:
        return await AssessmentManagementService(session).list_templates(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as error:
        raise _controlled(error) from error


@router.get(
    "/assignments",
    response_model=list[ManagerAssignmentResponse],
    responses=ERRORS,
)
async def list_management_assignments(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    assignment_status: Annotated[
        Literal["assigned", "in_progress", "completed", "revoked"] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    after: UUID | None = None,
) -> list[dict[str, Any]]:
    _no_store(response)
    try:
        return await AssessmentManagementService(session).list_assignments(
            principal.account_id,
            company_id,
            datetime.now(timezone.utc),
            status=assignment_status,
            limit=limit,
            after=after,
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post("/assignments", response_model=ManagerAssignmentResponse, responses=ERRORS)
async def create_management_assignment(
    company_id: UUID,
    request: CreateAssignmentRequest,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        value = await AssessmentManagementService(session).create_assignment(
            CreateAssignment(
                account_id=principal.account_id,
                company_id=company_id,
                employee_profile_id=request.employee_profile_id,
                template_version_id=request.template_version_id,
                venue_id=request.venue_id,
                due_at=request.due_at,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return value
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.post(
    "/measurements",
    response_model=AttemptDocumentResponse,
    responses=ERRORS,
)
async def start_management_measurement(
    company_id: UUID,
    request: StartManagerMeasurementRequest,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        value = await AssessmentManagementService(session).start_manager_measurement(
            StartManagerMeasurement(
                account_id=principal.account_id,
                company_id=company_id,
                subject_employee_profile_id=request.employee_profile_id,
                template_version_id=request.template_version_id,
                venue_id=request.venue_id,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return value
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/assignments/{assignment_id}",
    response_model=ManagerAssignmentResponse,
    responses=ERRORS,
)
async def get_management_assignment(
    company_id: UUID,
    assignment_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        return await AssessmentManagementService(session).assignment_detail(
            principal.account_id,
            company_id,
            assignment_id,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/assignments/{assignment_id}/revoke",
    response_model=ManagerAssignmentResponse,
    responses=ERRORS,
)
async def revoke_management_assignment(
    company_id: UUID,
    assignment_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        value = await AssessmentManagementService(session).revoke_assignment(
            principal.account_id,
            company_id,
            assignment_id,
            datetime.now(timezone.utc),
        )
        await session.commit()
        return value
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error
