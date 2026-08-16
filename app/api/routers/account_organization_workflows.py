"""Strict Account APIs for organization onboarding and task workflows."""

from contextlib import suppress
from datetime import date, datetime, timezone
import hashlib
import hmac
import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
    require_web_request,
)
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.infra.media import (
    MediaStoreUnavailable,
    get_task_media_store,
    task_media_enabled,
)
from app.internal.services.organization_workflow_service import (
    ActivateGroupRegistration,
    CancelTask,
    CreateGroupInvitation,
    CreatePosition,
    CreateTaskDraft,
    DispatchTask,
    JoinGroupInvitation,
    OrganizationWorkflowConflict,
    OrganizationWorkflowInvalid,
    OrganizationWorkflowNotFound,
    OrganizationWorkflowService,
    OrganizationWorkflowUnavailable,
    TransitionTaskAssignment,
    UpdateEmployeeBirthDate,
    UpdateTaskDraft,
)
from app.internal.services.task_media_service import (
    MAX_PHOTO_BYTES,
    ReserveTaskPhoto,
    TaskMediaService,
)
from app.settings import config


router = APIRouter(prefix="/api/v1/account", tags=["account-organization-workflows"])
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowErrorDetail(StrictModel):
    code: Literal[
        "workflow_resource_not_found",
        "invalid_workflow_request",
        "workflow_conflict",
        "workflow_unavailable",
        "workflow_storage_unavailable",
        "group_onboarding_legal_pending",
    ]


class WorkflowError(StrictModel):
    detail: WorkflowErrorDetail


class AccessPresetResponse(StrictModel):
    code: Literal[
        "owner",
        "organization_manager",
        "venue_manager",
        "employee_venue",
        "employee_unassigned",
    ]
    title: str
    scope: Literal["self", "working_venues", "explicit_venues", "company"]
    assignable: bool
    description: str


class PositionResponse(StrictModel):
    position_id: UUID
    name: str
    description: str | None
    sort_order: int
    access_preset: Literal[
        "owner",
        "organization_manager",
        "venue_manager",
        "employee_venue",
        "employee_unassigned",
    ]
    revision: datetime


class CreatePositionRequest(StrictModel):
    request_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    access_preset: Literal[
        "organization_manager",
        "venue_manager",
        "employee_venue",
        "employee_unassigned",
    ]
    sort_order: int = Field(ge=0, le=1000)


class GroupInvitationResponse(StrictModel):
    invitation_id: UUID
    company_id: UUID
    venue_id: UUID
    position_id: UUID
    label: str
    status: Literal["active", "revoked", "expired"]
    max_registrations: int
    registration_count: int
    expires_at: datetime
    join_path: str | None


class CreateGroupInvitationRequest(StrictModel):
    request_id: UUID
    venue_id: UUID
    position_id: UUID
    label: str = Field(min_length=1, max_length=160)
    expires_at: datetime
    max_registrations: int = Field(default=50, ge=1, le=200)


class JoinGroupInvitationRequest(StrictModel):
    token: str = Field(min_length=43, max_length=43)
    request_id: UUID
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    birth_date: date

    @field_validator("birth_date", mode="before")
    @classmethod
    def require_calendar_date(cls, value: object) -> object:
        return _calendar_date_input(value)


class EmployeeBirthDateResponse(StrictModel):
    employee_profile_id: UUID
    birth_date: date | None
    revision: datetime


class UpdateEmployeeBirthDateRequest(StrictModel):
    expected_birth_date: date | None
    birth_date: date

    @field_validator("expected_birth_date", "birth_date", mode="before")
    @classmethod
    def require_calendar_dates(cls, value: object) -> object:
        return None if value is None else _calendar_date_input(value)


class EmployeeBirthDateAuditResponse(StrictModel):
    actor_account_id: UUID
    previous_birth_date: date | None
    birth_date: date
    source: Literal["group_onboarding", "employee_update", "manager_update"]
    changed_at: datetime


class GroupRegistrationResponse(StrictModel):
    registration_id: UUID
    company_id: UUID
    venue_id: UUID
    employee_profile_id: UUID
    display_name: str
    status: Literal["pending_activation", "active", "rejected"]
    created_at: datetime
    activated_at: datetime | None


class CreateTaskRequest(StrictModel):
    request_id: UUID
    venue_id: UUID
    assessment_attempt_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class DispatchTaskRequest(StrictModel):
    employee_profile_ids: list[UUID] = Field(min_length=1, max_length=100)
    expected_version: int = Field(ge=1)


class UpdateTaskRequest(StrictModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class TaskResponse(StrictModel):
    task_id: UUID
    company_id: UUID
    venue_id: UUID
    assessment_attempt_id: UUID | None
    title: str
    description: str | None
    status: Literal["draft", "assigned", "completed", "cancelled"]
    version: int
    assignment_count: int
    task_assignment_id: UUID | None
    assignment_status: (
        Literal["assigned", "submitted_for_review", "changes_requested", "accepted"]
        | None
    )
    assignment_version: int | None
    photo_count: int
    created_at: datetime
    updated_at: datetime


class TransitionTaskRequest(StrictModel):
    action: Literal["submit", "request_changes", "accept"]
    expected_version: int = Field(ge=1)


class TaskAssignmentResponse(StrictModel):
    task_assignment_id: UUID
    task_id: UUID
    task_status: Literal["draft", "assigned", "completed", "cancelled"]
    status: Literal["assigned", "submitted_for_review", "changes_requested", "accepted"]
    version: int
    submitted_at: datetime | None
    reviewed_at: datetime | None
    photo_count: int


class TaskEventResponse(StrictModel):
    event_type: Literal[
        "task_created",
        "task_updated",
        "task_cancelled",
        "task_dispatched",
        "assignment_submitted_for_review",
        "assignment_changes_requested",
        "assignment_accepted",
        "task_completed",
    ]
    occurred_at: datetime


class TaskAssigneeResponse(StrictModel):
    employee_profile_id: UUID
    display_name: str
    position_name: str


class TaskPhotoResponse(StrictModel):
    photo_id: UUID
    task_id: UUID
    task_assignment_id: UUID | None
    mime_type: Literal["image/jpeg", "image/png"]
    byte_size: int = Field(ge=1, le=MAX_PHOTO_BYTES)
    status: Literal["ready", "deleted"]


class TaskMediaCapabilityResponse(StrictModel):
    enabled: bool


ERRORS = {
    401: {"model": PublicError},
    404: {"model": WorkflowError},
    409: {"model": WorkflowError},
    410: {"model": WorkflowError},
    422: {"model": WorkflowError},
    503: {"model": WorkflowError},
}


def _service(session: AsyncSession) -> OrganizationWorkflowService:
    return OrganizationWorkflowService(
        session,
        invitation_pepper=config.ACCOUNT_GROUP_INVITATION_PEPPER.encode("utf-8"),
    )


def _controlled(error: Exception) -> HTTPException:
    if isinstance(error, OrganizationWorkflowNotFound):
        code, http = "workflow_resource_not_found", status.HTTP_404_NOT_FOUND
    elif isinstance(error, OrganizationWorkflowInvalid):
        code, http = "invalid_workflow_request", status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(error, OrganizationWorkflowConflict):
        code, http = "workflow_conflict", status.HTTP_409_CONFLICT
    elif isinstance(error, OrganizationWorkflowUnavailable):
        code, http = "workflow_unavailable", status.HTTP_410_GONE
    elif isinstance(error, MediaStoreUnavailable):
        code, http = "workflow_storage_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        raise error
    return HTTPException(
        status_code=http,
        detail={"code": code},
        headers={"Cache-Control": NO_STORE},
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = NO_STORE


def _calendar_date_input(value: object) -> object:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise ValueError("birth_date must be an ISO calendar date")


def _require_group_onboarding_legal_publication() -> None:
    if not config.ACCOUNT_GROUP_ONBOARDING_DOB_LEGAL_PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "group_onboarding_legal_pending"},
            headers={"Cache-Control": NO_STORE},
        )


def _require_task_media() -> None:
    if not task_media_enabled():
        raise MediaStoreUnavailable("private media storage is unavailable")


@router.get(
    "/organization/access-presets",
    response_model=list[AccessPresetResponse],
    responses=ERRORS,
)
async def list_access_presets(
    response: Response,
    _: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    return await _service(session).list_access_presets()


@router.get(
    "/companies/{company_id}/organization/positions",
    response_model=list[PositionResponse],
    responses=ERRORS,
)
async def list_positions(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).list_positions(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/companies/{company_id}/organization/positions",
    response_model=PositionResponse,
    responses=ERRORS,
)
async def create_position(
    company_id: UUID,
    body: CreatePositionRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await _service(session).create_position(
            CreatePosition(
                actor_account_id=principal.account_id,
                company_id=company_id,
                request_id=body.request_id,
                name=body.name,
                description=body.description,
                access_preset=body.access_preset,
                sort_order=body.sort_order,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/companies/{company_id}/organization/group-invitations",
    response_model=list[GroupInvitationResponse],
    responses=ERRORS,
)
async def list_group_invitations(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).list_group_invitations(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/companies/{company_id}/organization/group-invitations",
    response_model=GroupInvitationResponse,
    responses=ERRORS,
)
async def create_group_invitation(
    company_id: UUID,
    body: CreateGroupInvitationRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    _require_group_onboarding_legal_publication()
    try:
        result = await _service(session).create_group_invitation(
            CreateGroupInvitation(
                actor_account_id=principal.account_id,
                company_id=company_id,
                request_id=body.request_id,
                venue_id=body.venue_id,
                position_id=body.position_id,
                label=body.label,
                expires_at=body.expires_at,
                max_registrations=body.max_registrations,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.delete(
    "/companies/{company_id}/organization/group-invitations/{invitation_id}",
    response_model=GroupInvitationResponse,
    responses=ERRORS,
)
async def revoke_group_invitation(
    company_id: UUID,
    invitation_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await _service(session).revoke_group_invitation(
            principal.account_id,
            company_id,
            invitation_id,
            datetime.now(timezone.utc),
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.post(
    "/organization/group-invitations/join",
    response_model=GroupRegistrationResponse,
    responses=ERRORS,
)
async def join_group_invitation(
    body: JoinGroupInvitationRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    _require_group_onboarding_legal_publication()
    try:
        result = await _service(session).join_group_invitation(
            JoinGroupInvitation(
                actor_account_id=principal.account_id,
                token=body.token,
                request_id=body.request_id,
                first_name=body.first_name,
                last_name=body.last_name,
                birth_date=body.birth_date,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/companies/{company_id}/organization/employees/{employee_profile_id}/birth-date",
    response_model=EmployeeBirthDateResponse,
    responses=ERRORS,
)
async def get_employee_birth_date(
    company_id: UUID,
    employee_profile_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    _no_store(response)
    try:
        return await _service(session).employee_birth_date(
            principal.account_id,
            company_id,
            employee_profile_id,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.put(
    "/companies/{company_id}/organization/employees/{employee_profile_id}/birth-date",
    response_model=EmployeeBirthDateResponse,
    responses=ERRORS,
)
async def update_employee_birth_date(
    company_id: UUID,
    employee_profile_id: UUID,
    body: UpdateEmployeeBirthDateRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await _service(session).update_employee_birth_date(
            UpdateEmployeeBirthDate(
                actor_account_id=principal.account_id,
                company_id=company_id,
                employee_profile_id=employee_profile_id,
                expected_birth_date=body.expected_birth_date,
                birth_date=body.birth_date,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/companies/{company_id}/organization/employees/{employee_profile_id}/birth-date/audit",
    response_model=list[EmployeeBirthDateAuditResponse],
    responses=ERRORS,
)
async def list_employee_birth_date_audit(
    company_id: UUID,
    employee_profile_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).employee_birth_date_audit(
            principal.account_id,
            company_id,
            employee_profile_id,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.get(
    "/companies/{company_id}/organization/pending-registrations",
    response_model=list[GroupRegistrationResponse],
    responses=ERRORS,
)
async def list_pending_registrations(
    company_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).list_pending_registrations(
            principal.account_id, company_id, datetime.now(timezone.utc)
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/companies/{company_id}/organization/pending-registrations/{registration_id}/activate",
    response_model=GroupRegistrationResponse,
    responses=ERRORS,
)
async def activate_group_registration(
    company_id: UUID,
    registration_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await _service(session).activate_group_registration(
            ActivateGroupRegistration(
                actor_account_id=principal.account_id,
                company_id=company_id,
                registration_id=registration_id,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/task-media/capability",
    response_model=TaskMediaCapabilityResponse,
    responses={401: {"model": PublicError}},
)
async def task_media_capability(
    response: Response,
    _: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
) -> dict[str, bool]:
    _no_store(response)
    return {"enabled": task_media_enabled()}


@router.get(
    "/companies/{company_id}/tasks",
    response_model=list[TaskResponse],
    responses=ERRORS,
)
async def list_tasks(
    company_id: UUID,
    view: Literal["mine", "created", "review"],
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).list_tasks(
            principal.account_id,
            company_id,
            view,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.get(
    "/companies/{company_id}/tasks/assignees",
    response_model=list[TaskAssigneeResponse],
    responses=ERRORS,
)
async def list_task_assignees(
    company_id: UUID,
    venue_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).list_task_assignees(
            principal.account_id,
            company_id,
            venue_id,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.get(
    "/companies/{company_id}/tasks/{task_id}/history",
    response_model=list[TaskEventResponse],
    responses=ERRORS,
)
async def task_history(
    company_id: UUID,
    task_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        return await _service(session).task_history(
            principal.account_id,
            company_id,
            task_id,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/companies/{company_id}/tasks",
    response_model=TaskResponse,
    responses=ERRORS,
)
async def create_task(
    company_id: UUID,
    body: CreateTaskRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        _require_task_media()
        result = await _service(session).create_task_draft(
            CreateTaskDraft(
                actor_account_id=principal.account_id,
                company_id=company_id,
                venue_id=body.venue_id,
                request_id=body.request_id,
                assessment_attempt_id=body.assessment_attempt_id,
                title=body.title,
                description=body.description,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.put(
    "/companies/{company_id}/tasks/{task_id}",
    response_model=TaskResponse,
    responses=ERRORS,
)
async def update_task(
    company_id: UUID,
    task_id: UUID,
    body: UpdateTaskRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await _service(session).update_task_draft(
            UpdateTaskDraft(
                actor_account_id=principal.account_id,
                company_id=company_id,
                task_id=task_id,
                expected_version=body.expected_version,
                title=body.title,
                description=body.description,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.delete(
    "/companies/{company_id}/tasks/{task_id}",
    response_model=TaskResponse,
    responses=ERRORS,
)
async def cancel_task(
    company_id: UUID,
    task_id: UUID,
    expected_version: int,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        result = await _service(session).cancel_task(
            CancelTask(
                actor_account_id=principal.account_id,
                company_id=company_id,
                task_id=task_id,
                expected_version=expected_version,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.post(
    "/companies/{company_id}/tasks/{task_id}/dispatch",
    response_model=TaskResponse,
    responses=ERRORS,
)
async def dispatch_task(
    company_id: UUID,
    task_id: UUID,
    body: DispatchTaskRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        _require_task_media()
        result = await _service(session).dispatch_task(
            DispatchTask(
                actor_account_id=principal.account_id,
                company_id=company_id,
                task_id=task_id,
                employee_profile_ids=tuple(body.employee_profile_ids),
                expected_version=body.expected_version,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.post(
    "/companies/{company_id}/task-assignments/{task_assignment_id}/transition",
    response_model=TaskAssignmentResponse,
    responses=ERRORS,
)
async def transition_task_assignment(
    company_id: UUID,
    task_assignment_id: UUID,
    body: TransitionTaskRequest,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    try:
        _require_task_media()
        result = await _service(session).transition_task_assignment(
            TransitionTaskAssignment(
                actor_account_id=principal.account_id,
                company_id=company_id,
                task_assignment_id=task_assignment_id,
                action=body.action,
                expected_version=body.expected_version,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/companies/{company_id}/tasks/{task_id}/photos",
    response_model=list[TaskPhotoResponse],
    responses=ERRORS,
)
async def list_task_photos(
    company_id: UUID,
    task_id: UUID,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    task_assignment_id: UUID | None = None,
) -> list[dict[str, object]]:
    _no_store(response)
    try:
        _require_task_media()
        return await TaskMediaService(session).list_photos(
            principal.account_id,
            company_id,
            task_id,
            task_assignment_id,
            datetime.now(timezone.utc),
        )
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/companies/{company_id}/tasks/{task_id}/photos",
    response_model=TaskPhotoResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def upload_task_photo(
    company_id: UUID,
    task_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    photo: Annotated[UploadFile, File(description="JPEG or PNG task evidence")],
    task_assignment_id: UUID | None = None,
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    reserved = None
    store = None
    try:
        _require_task_media()
        content = await photo.read(MAX_PHOTO_BYTES + 1)
        reserved = await TaskMediaService(session).reserve(
            ReserveTaskPhoto(
                actor_account_id=principal.account_id,
                company_id=company_id,
                task_id=task_id,
                task_assignment_id=task_assignment_id,
                declared_mime_type=photo.content_type or "",
                content=content,
                now=datetime.now(timezone.utc),
            )
        )
        store = get_task_media_store()
        await store.verify_security()
        await store.put_temporary(
            reserved.temporary_object_key,
            reserved.content,
            reserved.mime_type,
        )
        await store.promote(
            reserved.temporary_object_key,
            reserved.final_object_key,
        )
        result = await TaskMediaService(session).mark_ready(
            company_id,
            reserved.photo_id,
            reserved.digest,
            datetime.now(timezone.utc),
            reserved.final_object_key,
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        if reserved is not None and store is not None:
            with suppress(MediaStoreUnavailable):
                await store.delete(reserved.temporary_object_key)
            with suppress(MediaStoreUnavailable):
                await store.delete(reserved.final_object_key)
        raise _controlled(error) from error
    finally:
        await photo.close()


@router.get(
    "/companies/{company_id}/tasks/{task_id}/photos/{photo_id}/content",
    response_class=Response,
    responses={
        **ERRORS,
        200: {
            "description": "Authorized task evidence image",
            "content": {
                "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
                "image/png": {"schema": {"type": "string", "format": "binary"}},
            },
        },
    },
)
async def download_task_photo(
    company_id: UUID,
    task_id: UUID,
    photo_id: UUID,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> Response:
    try:
        _require_task_media()
        authorized = await TaskMediaService(session).authorize_download(
            principal.account_id,
            company_id,
            photo_id,
            datetime.now(timezone.utc),
            task_id=task_id,
        )
        store = get_task_media_store()
        content = await store.get(authorized.object_key, MAX_PHOTO_BYTES)
        if len(content) != authorized.byte_size or not hmac.compare_digest(
            hashlib.sha256(content).digest(), authorized.digest
        ):
            raise MediaStoreUnavailable("private media object is invalid")
        extension = "jpg" if authorized.mime_type == "image/jpeg" else "png"
        return Response(
            content=content,
            media_type=authorized.mime_type,
            headers={
                "Cache-Control": NO_STORE,
                "Content-Disposition": f'inline; filename="task-photo.{extension}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as error:
        raise _controlled(error) from error


@router.delete(
    "/companies/{company_id}/tasks/{task_id}/photos/{photo_id}",
    response_model=TaskPhotoResponse,
    responses=ERRORS,
)
async def delete_task_photo(
    company_id: UUID,
    task_id: UUID,
    photo_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[
        CurrentAccountPrincipal, Depends(get_current_account_principal)
    ],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, object]:
    require_web_request(request)
    _no_store(response)
    service = TaskMediaService(session)
    try:
        _require_task_media()
        deletion = await service.begin_delete(
            principal.account_id,
            company_id,
            task_id,
            photo_id,
            datetime.now(timezone.utc),
        )
        if deletion.already_deleted:
            await session.commit()
            return deletion.photo
        await session.commit()
        store = get_task_media_store()
        await store.delete(deletion.object_key)
        result = await TaskMediaService(session).finalize_delete(
            company_id,
            photo_id,
            datetime.now(timezone.utc),
        )
        await session.commit()
        return result
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error
