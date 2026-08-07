"""Authenticated employee assessment assignment and attempt HTTP boundary."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import PublicError, get_account_auth_session
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.assessment_attempt_service import (
    AnswerInput,
    AssessmentAttemptIncomplete,
    AssessmentAttemptInvalid,
    AssessmentAttemptNotFound,
    AssessmentAttemptReadOnly,
    AssessmentAttemptRevisionConflict,
    AssessmentAttemptService,
    ReplaceDraft,
)


router = APIRouter(prefix="/api/v1/account", tags=["account-assessments"])
NO_STORE = "private, no-store"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnswerRequest(StrictModel):
    item_id: UUID
    answer_type: str = Field(min_length=1, max_length=30)
    value: Any


class ReplaceDraftRequest(StrictModel):
    expected_revision: int = Field(ge=0)
    answers: list[AnswerRequest] = Field(max_length=5_000)


class AttemptAnswerResponse(StrictModel):
    item_id: UUID
    answer_type: Literal[
        "boolean", "score", "integer", "decimal", "text",
        "single_choice", "multi_choice", "date", "time",
    ]
    value: bool | int | str | list[UUID]


class AssessmentInputConfigResponse(StrictModel):
    placeholder: str | None = None
    max_length: int | None = Field(default=None, ge=0)


class AssessmentOptionResponse(StrictModel):
    id: UUID
    label: str
    sort_order: int


class AssessmentItemResponse(StrictModel):
    id: UUID
    prompt: str
    guidance: str | None
    answer_type: Literal[
        "boolean", "score", "integer", "decimal", "text",
        "single_choice", "multi_choice", "date", "time",
    ]
    required: bool
    sort_order: int
    config: AssessmentInputConfigResponse
    options: list[AssessmentOptionResponse]


class AssessmentSectionResponse(StrictModel):
    id: UUID
    parent_section_id: UUID | None
    title: str
    description: str | None
    sort_order: int
    items: list[AssessmentItemResponse]


class AssessmentTemplateDocumentResponse(StrictModel):
    version_id: UUID
    sections: list[AssessmentSectionResponse]


class AssessmentAssignmentSummaryResponse(StrictModel):
    id: UUID
    company_id: UUID
    status: Literal["assigned", "in_progress", "completed", "revoked"]
    assigned_at: datetime
    due_at: datetime | None
    template_name: str
    template_version: int
    read_only: bool


class AssessmentAssignmentDetailResponse(AssessmentAssignmentSummaryResponse):
    document: AssessmentTemplateDocumentResponse


class AttemptDocumentResponse(StrictModel):
    id: UUID
    assignment_id: UUID
    status: Literal["draft", "submitted"]
    revision: int
    started_at: datetime
    last_saved_at: datetime | None
    submitted_at: datetime | None
    read_only: bool
    read_only_reason: Literal["submitted", "revoked", "expired"] | None
    document: AssessmentTemplateDocumentResponse
    answers: list[AttemptAnswerResponse]


class AssessmentCompletionResponse(StrictModel):
    scoring_algorithm: Literal["completion_v1"]
    submitted_at: datetime
    answered_count: int = Field(ge=0)
    required_count: int = Field(ge=0)
    total_count: int = Field(ge=0)


class AssessmentSubmissionResponse(AssessmentCompletionResponse):
    pass


class AssessmentResultResponse(AssessmentCompletionResponse):
    pass


class RevisionConflictDetail(StrictModel):
    code: str
    current_revision: int
    answers: list[AttemptAnswerResponse]


class RevisionConflictResponse(StrictModel):
    detail: RevisionConflictDetail


def _error(code: str, http_status: int) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"code": code},
        headers={"Cache-Control": NO_STORE},
    )


def _controlled(error: Exception) -> HTTPException:
    if isinstance(error, AssessmentAttemptNotFound):
        return _error("assessment_not_found", status.HTTP_404_NOT_FOUND)
    if isinstance(error, AssessmentAttemptReadOnly):
        return _error("assessment_read_only", status.HTTP_409_CONFLICT)
    if isinstance(error, AssessmentAttemptIncomplete):
        return _error("assessment_incomplete", status.HTTP_409_CONFLICT)
    if isinstance(error, AssessmentAttemptInvalid):
        return _error("invalid_assessment_answers", status.HTTP_400_BAD_REQUEST)
    raise error


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = NO_STORE


@router.get(
    "/assessment-assignments",
    response_model=list[AssessmentAssignmentSummaryResponse],
    responses={401: {"model": PublicError}},
)
async def list_assignments(
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict[str, Any]]:
    _no_store(response)
    return await AssessmentAttemptService(session).list_assignments(principal.account_id, datetime.now(timezone.utc))


@router.get(
    "/assessment-assignments/{assignment_id}",
    response_model=AssessmentAssignmentDetailResponse,
    responses={401: {"model": PublicError}, 404: {"model": PublicError}},
)
async def get_assignment(
    assignment_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        return await AssessmentAttemptService(session).assignment_detail(principal.account_id, assignment_id, datetime.now(timezone.utc))
    except Exception as error:
        raise _controlled(error) from error


@router.post(
    "/assessment-assignments/{assignment_id}/attempt",
    response_model=AttemptDocumentResponse,
    responses={
        401: {"model": PublicError},
        404: {"model": PublicError},
        409: {"model": PublicError},
    },
)
async def create_or_resume_attempt(
    assignment_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        value = await AssessmentAttemptService(session).create_or_resume(principal.account_id, assignment_id, datetime.now(timezone.utc))
        await session.commit()
        return value
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/assessment-attempts/{attempt_id}",
    response_model=AttemptDocumentResponse,
    responses={401: {"model": PublicError}, 404: {"model": PublicError}},
)
async def get_attempt(
    attempt_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        return await AssessmentAttemptService(session).read_attempt(principal.account_id, attempt_id, datetime.now(timezone.utc))
    except Exception as error:
        raise _controlled(error) from error


@router.put(
    "/assessment-attempts/{attempt_id}/draft",
    response_model=AttemptDocumentResponse,
    responses={
        401: {"model": PublicError},
        409: {"model": RevisionConflictResponse},
    },
)
async def replace_attempt_draft(
    attempt_id: UUID,
    request: ReplaceDraftRequest,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> Any:
    _no_store(response)
    service = AssessmentAttemptService(session)
    try:
        value = await service.replace_draft(ReplaceDraft(
            account_id=principal.account_id,
            attempt_id=attempt_id,
            expected_revision=request.expected_revision,
            answers=[AnswerInput(value.item_id, value.answer_type, value.value) for value in request.answers],
            now=datetime.now(timezone.utc),
        ))
        await session.commit()
        return value
    except AssessmentAttemptRevisionConflict as error:
        await session.rollback()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            headers={"Cache-Control": NO_STORE},
            content={
                "detail": {
                    "code": "assessment_revision_conflict",
                    "current_revision": error.current_revision,
                    "answers": [
                        {**answer, "item_id": str(answer["item_id"])}
                        for answer in error.answers
                    ],
                }
            },
        )
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.post(
    "/assessment-attempts/{attempt_id}/submit",
    response_model=AssessmentSubmissionResponse,
    responses={
        401: {"model": PublicError},
        404: {"model": PublicError},
        409: {"model": PublicError},
    },
)
async def submit_attempt(
    attempt_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        value = await AssessmentAttemptService(session).submit(principal.account_id, attempt_id, datetime.now(timezone.utc))
        await session.commit()
        return value
    except Exception as error:
        await session.rollback()
        raise _controlled(error) from error


@router.get(
    "/assessment-attempts/{attempt_id}/result",
    response_model=AssessmentResultResponse,
    responses={401: {"model": PublicError}, 404: {"model": PublicError}},
)
async def get_attempt_result(
    attempt_id: UUID,
    response: Response,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict[str, Any]:
    _no_store(response)
    try:
        return await AssessmentAttemptService(session).result(principal.account_id, attempt_id, datetime.now(timezone.utc))
    except Exception as error:
        raise _controlled(error) from error
