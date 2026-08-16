"""Authenticated HTTP boundary for assessment library and company drafts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.account_auth import get_current_account_principal
from app.api.routers.account_invitation_auth import (
    PublicError,
    get_account_auth_session,
)
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.account_access_token_service import CurrentAccountPrincipal
from app.internal.services.assessment_catalog_service import (
    AssessmentCatalogNotFound,
    AssessmentCatalogService,
    ListLibraryTemplates,
)
from app.internal.services.assessment_draft_service import (
    AssessmentDraftNotEditable,
    AssessmentDraftNotFound,
    AssessmentDraftRevisionConflict,
    AssessmentDraftStructureInvalid,
    AssessmentDraftService,
    DraftItemInput,
    DraftOptionInput,
    DraftSectionInput,
    InvalidAssessmentDraftRequest,
    SaveDraftDocument,
)
from app.internal.services.assessment_template_service import (
    AdoptLibraryTemplate,
    AssessmentMethodologyNotFound,
    AssessmentTemplateCodeConflict,
    AssessmentTemplateDraftExists,
    AssessmentTemplateNotEditable,
    AssessmentTemplateNotFound,
    AssessmentTemplatePublicationInvalid,
    AssessmentTemplateService,
    AssessmentTemplateSourceInvalid,
    AssessmentTemplateVersionConflict,
    CreateNextDraft,
    InvalidAssessmentTemplateRequest,
    PublishTemplateVersion,
)


router = APIRouter(prefix="/api/v1", tags=["assessment-templates"])
READ_PERMISSION = "assessment.template.read"
MANAGE_PERMISSION = "assessment.template.manage"
_ACTIVITY_TYPES = {
    "evaluation", "measurement", "walkthrough", "checklist",
    "test", "survey", "attestation",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdoptAssessmentRequest(StrictModel):
    source_library_version_id: UUID
    company_template_code: str = Field(min_length=1, max_length=100)
    company_template_name: str | None = Field(default=None, min_length=1, max_length=255)
    local_description: str | None = Field(default=None, max_length=10_000)


class DraftOptionRequest(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=255)
    sort_order: int = Field(ge=0)
    numeric_value: Decimal | None = None
    is_disqualifying: bool = False


class DraftItemRequest(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=10_000)
    guidance: str | None = Field(default=None, max_length=10_000)
    response_type: str = Field(min_length=1, max_length=30)
    is_required: bool = False
    sort_order: int = Field(ge=0)
    weight: Decimal | None = Field(default=None, ge=0)
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    passing_value: Decimal | None = None
    evidence_mode: str = Field(min_length=1, max_length=30)
    criticality: str = Field(min_length=1, max_length=20)
    config: dict[str, Any] = Field(default_factory=dict)
    options: list[DraftOptionRequest] = Field(default_factory=list, max_length=20_000)


class DraftSectionRequest(StrictModel):
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    section_kind: str = Field(min_length=1, max_length=20)
    sort_order: int = Field(ge=0)
    weight: Decimal | None = Field(default=None, ge=0)
    parent_code: str | None = Field(default=None, max_length=100)
    items: list[DraftItemRequest] = Field(default_factory=list, max_length=5_000)


class SaveAssessmentDraftRequest(StrictModel):
    expected_edit_revision: int = Field(ge=1)
    template_name: str | None = Field(default=None, min_length=1, max_length=255)
    local_description: str | None = Field(default=None, max_length=10_000)
    change_note: str | None = Field(default=None, max_length=10_000)
    sections: list[DraftSectionRequest] = Field(max_length=200)

    @model_validator(mode="after")
    def validate_document_limits(self):
        items = sum(len(section.items) for section in self.sections)
        options = sum(
            len(item.options)
            for section in self.sections
            for item in section.items
        )
        if items > 5_000 or options > 20_000:
            raise ValueError("assessment document exceeds safe limits")
        for section in self.sections:
            for item in section.items:
                encoded = json.dumps(
                    item.config,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                if len(encoded) > 100_000:
                    raise ValueError("config exceeds safe size")
                _validate_json(item.config)
        return self


class NextDraftRequest(StrictModel):
    change_note: str | None = Field(default=None, max_length=10_000)


def _validate_json(value: Any, *, depth: int = 0) -> None:
    if depth > 20:
        raise ValueError("config exceeds safe depth")
    if isinstance(value, dict):
        if len(value) > 1_000:
            raise ValueError("config exceeds safe size")
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > 255:
                raise ValueError("config key is invalid")
            _validate_json(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 5_000:
            raise ValueError("config exceeds safe size")
        for child in value:
            _validate_json(child, depth=depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("config contains unsupported value")
    elif isinstance(value, str) and len(value) > 10_000:
        raise ValueError("config text exceeds safe size")


def _error(http_status: int, code: str) -> HTTPException:
    return HTTPException(
        status_code=http_status,
        detail={"code": code},
        headers={"Cache-Control": "private, no-store"},
    )


async def _authorize(
    session: AsyncSession,
    principal: CurrentAccountPrincipal,
    company_id: UUID,
    permission: str,
) -> None:
    if not await AccessDecisionService(session).can_in_company(
        principal.account_id, company_id, permission
    ):
        raise _error(status.HTTP_403_FORBIDDEN, "permission_denied")


def _option(value: DraftOptionRequest) -> DraftOptionInput:
    return DraftOptionInput(
        value.code, value.label, value.sort_order,
        value.numeric_value, value.is_disqualifying,
    )


def _item(value: DraftItemRequest) -> DraftItemInput:
    return DraftItemInput(
        code=value.code,
        prompt=value.prompt,
        guidance=value.guidance,
        response_type=value.response_type,
        is_required=value.is_required,
        sort_order=value.sort_order,
        weight=value.weight,
        min_value=value.min_value,
        max_value=value.max_value,
        passing_value=value.passing_value,
        evidence_mode=value.evidence_mode,
        criticality=value.criticality,
        config=value.config,
        options=[_option(option) for option in value.options],
    )


def _section(value: DraftSectionRequest) -> DraftSectionInput:
    return DraftSectionInput(
        code=value.code,
        title=value.title,
        description=value.description,
        section_kind=value.section_kind,
        sort_order=value.sort_order,
        weight=value.weight,
        parent_code=value.parent_code,
        items=[_item(item) for item in value.items],
    )


def _raise_controlled(error: Exception) -> None:
    if isinstance(error, AssessmentDraftRevisionConflict):
        raise _error(409, "assessment_revision_conflict") from error
    if isinstance(error, AssessmentTemplateCodeConflict):
        raise _error(409, "assessment_code_conflict") from error
    if isinstance(error, (
        AssessmentTemplateDraftExists, AssessmentTemplateVersionConflict
    )):
        raise _error(409, "assessment_draft_exists") from error
    if isinstance(error, (
        AssessmentCatalogNotFound, AssessmentTemplateNotFound,
        AssessmentMethodologyNotFound, AssessmentDraftNotFound,
        AssessmentTemplateNotEditable, AssessmentDraftNotEditable,
        AssessmentTemplateSourceInvalid,
    )):
        raise _error(404, "assessment_not_found") from error
    if isinstance(error, AssessmentTemplatePublicationInvalid):
        raise _error(400, "assessment_publication_invalid") from error
    if isinstance(error, (
        InvalidAssessmentTemplateRequest, InvalidAssessmentDraftRequest,
        AssessmentDraftStructureInvalid,
    )):
        raise _error(400, "invalid_assessment_request") from error
    raise error


@router.get("/assessment-library", responses={401: {"model": PublicError}})
async def list_library(
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
    activity_type: str | None = Query(default=None),
    query: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    del principal
    if activity_type is not None and activity_type not in _ACTIVITY_TYPES:
        raise _error(400, "invalid_assessment_request")
    return await AssessmentCatalogService(session).list_library_templates(
        ListLibraryTemplates(activity_type, query, limit, offset)
    )


@router.get("/assessment-library/{template_id}")
async def get_library_latest(
    template_id: UUID,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict:
    del principal
    try:
        return await AssessmentCatalogService(session).get_library_template(template_id)
    except Exception as error:
        _raise_controlled(error)


@router.get("/assessment-library/{template_id}/versions/{version_id}")
async def get_library_version(
    template_id: UUID,
    version_id: UUID,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict:
    del principal
    try:
        return await AssessmentCatalogService(session).get_library_template(
            template_id, version_id
        )
    except Exception as error:
        _raise_controlled(error)


@router.get("/companies/{company_id}/assessment-templates")
async def list_company(
    company_id: UUID,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> list[dict]:
    await _authorize(session, principal, company_id, READ_PERMISSION)
    return await AssessmentCatalogService(session).list_company_templates(company_id)


@router.post(
    "/companies/{company_id}/assessment-templates/adopt",
    status_code=status.HTTP_201_CREATED,
)
async def adopt(
    company_id: UUID,
    body: AdoptAssessmentRequest,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict:
    await _authorize(session, principal, company_id, MANAGE_PERMISSION)
    try:
        result = await AssessmentTemplateService(session).adopt_library_template(
            AdoptLibraryTemplate(
                company_id=company_id,
                source_library_version_id=body.source_library_version_id,
                company_template_code=body.company_template_code,
                company_template_name=body.company_template_name,
                local_description=body.local_description,
                now=datetime.now(timezone.utc),
            )
        )
        await AssessmentTemplateService(session).publish_template_version(
            PublishTemplateVersion(
                template_id=result.company_template_id,
                template_version_id=result.draft_version_id,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result.__dict__
    except HTTPException:
        raise
    except Exception as error:
        await session.rollback()
        _raise_controlled(error)


@router.get(
    "/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}"
)
async def get_company_version(
    company_id: UUID,
    template_id: UUID,
    version_id: UUID,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict:
    await _authorize(session, principal, company_id, READ_PERMISSION)
    try:
        return await AssessmentCatalogService(session).get_company_template_version(
            company_id, template_id, version_id
        )
    except Exception as error:
        _raise_controlled(error)


@router.put(
    "/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}/draft"
)
async def save_draft(
    company_id: UUID,
    template_id: UUID,
    version_id: UUID,
    body: SaveAssessmentDraftRequest,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict:
    await _authorize(session, principal, company_id, MANAGE_PERMISSION)
    try:
        await AssessmentDraftService(session).save_draft_document(
            SaveDraftDocument(
                template_id=template_id,
                template_version_id=version_id,
                expected_edit_revision=body.expected_edit_revision,
                template_name=body.template_name,
                local_description=body.local_description,
                change_note=body.change_note,
                sections=[_section(section) for section in body.sections],
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return await AssessmentCatalogService(session).get_company_template_version(
            company_id, template_id, version_id
        )
    except HTTPException:
        raise
    except Exception as error:
        await session.rollback()
        _raise_controlled(error)


@router.post(
    "/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}/publish"
)
async def publish(
    company_id: UUID,
    template_id: UUID,
    version_id: UUID,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict:
    await _authorize(session, principal, company_id, MANAGE_PERMISSION)
    try:
        result = await AssessmentTemplateService(session).publish_template_version(
            PublishTemplateVersion(
                template_id=template_id,
                template_version_id=version_id,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result.__dict__
    except HTTPException:
        raise
    except Exception as error:
        await session.rollback()
        _raise_controlled(error)


@router.post(
    "/companies/{company_id}/assessment-templates/{template_id}/versions/{version_id}/next-draft",
    status_code=status.HTTP_201_CREATED,
)
async def next_draft(
    company_id: UUID,
    template_id: UUID,
    version_id: UUID,
    body: NextDraftRequest,
    principal: Annotated[CurrentAccountPrincipal, Depends(get_current_account_principal)],
    session: Annotated[AsyncSession, Depends(get_account_auth_session)],
) -> dict:
    await _authorize(session, principal, company_id, MANAGE_PERMISSION)
    try:
        result = await AssessmentTemplateService(session).create_next_draft(
            CreateNextDraft(
                template_id=template_id,
                source_published_version_id=version_id,
                change_note=body.change_note,
                now=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        return result.__dict__
    except HTTPException:
        raise
    except Exception as error:
        await session.rollback()
        _raise_controlled(error)
