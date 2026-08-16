"""Application-level mutation boundary for assessment template artifacts.

Published methodologies and template versions are immutable through this
service. Direct ORM writes are intentionally not prevented by database
triggers in v1; future editing commands must use ``assert_editable_draft``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.assessment_template import (
    AssessmentMethodology,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
)
from app.infra.database.models.assessment_metric import (
    AssessmentItemMetricMapping,
    AssessmentMetricDefinition,
    AssessmentScoringPolicy,
)
from app.infra.database.models.company import Company


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CHOICE_TYPES = {"single_choice", "multi_choice"}
_WEIGHTED_TYPES = {"boolean", "score", "integer", "decimal", "single_choice"}
_CANONICAL_METRICS = {
    "taste",
    "speed",
    "order",
    "service",
    "people",
    "space",
    "economics",
    "food_safety",
}


class AssessmentTemplateError(Exception):
    """Base controlled template lifecycle error."""


class InvalidAssessmentTemplateRequest(AssessmentTemplateError):
    pass


class AssessmentTemplateNotFound(AssessmentTemplateError):
    pass


class AssessmentMethodologyNotFound(AssessmentTemplateError):
    pass


class AssessmentTemplateNotEditable(AssessmentTemplateError):
    pass


class AssessmentTemplatePublicationInvalid(AssessmentTemplateError):
    pass


class AssessmentTemplateSourceInvalid(AssessmentTemplateError):
    pass


class AssessmentTemplateCodeConflict(AssessmentTemplateError):
    pass


class AssessmentTemplateDraftExists(AssessmentTemplateError):
    pass


class AssessmentTemplateVersionConflict(AssessmentTemplateError):
    pass


@dataclass(frozen=True)
class PublishMethodology:
    methodology_id: UUID
    now: datetime


@dataclass(frozen=True)
class PublishedMethodology:
    methodology_id: UUID
    status: str
    published_at: datetime


@dataclass(frozen=True)
class PublishTemplateVersion:
    template_id: UUID
    template_version_id: UUID
    now: datetime


@dataclass(frozen=True)
class PublishedTemplateVersion:
    template_id: UUID
    template_version_id: UUID
    version: int
    status: str
    published_at: datetime


@dataclass(frozen=True)
class AdoptLibraryTemplate:
    company_id: UUID
    source_library_version_id: UUID
    company_template_code: str
    now: datetime
    company_template_name: str | None = None
    local_description: str | None = None


@dataclass(frozen=True)
class AdoptedLibraryTemplate:
    company_template_id: UUID
    draft_version_id: UUID
    source_library_version_id: UUID
    methodology_id: UUID
    section_count: int
    item_count: int
    option_count: int


@dataclass(frozen=True)
class CreateNextDraft:
    template_id: UUID
    source_published_version_id: UUID
    now: datetime
    change_note: str | None = None


@dataclass(frozen=True)
class CreatedTemplateDraft:
    template_id: UUID
    draft_version_id: UUID
    version: int
    section_count: int
    item_count: int
    option_count: int


class AssessmentTemplateService:
    """Lifecycle service which never owns the caller's outer transaction."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def publish_methodology(
        self, request: PublishMethodology
    ) -> PublishedMethodology:
        self._validate_uuid("methodology_id", request.methodology_id)
        self._validate_now(request.now)
        async with self._session.begin_nested():
            methodology = (
                await self._session.execute(
                    select(AssessmentMethodology)
                    .where(AssessmentMethodology.id == request.methodology_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if methodology is None or methodology.deleted_at is not None:
                raise AssessmentMethodologyNotFound("methodology is unavailable")
            if methodology.status != "draft":
                raise AssessmentTemplatePublicationInvalid(
                    "methodology is not a publishable draft"
                )
            if not all(
                isinstance(value, str) and value.strip()
                for value in (methodology.code, methodology.title, methodology.body)
            ) or not _SLUG.fullmatch(methodology.code.strip().lower()):
                raise AssessmentTemplatePublicationInvalid(
                    "methodology content is incomplete"
                )
            if (methodology.owner_type == "system") != (methodology.company_id is None):
                raise AssessmentTemplatePublicationInvalid(
                    "methodology owner context is invalid"
                )
            methodology.code = methodology.code.strip().lower()
            methodology.title = methodology.title.strip()
            methodology.body = methodology.body.strip()
            methodology.status = "published"
            methodology.published_at = request.now
            methodology.updated_at = request.now
            await self._session.flush()
            return PublishedMethodology(
                methodology.id, methodology.status, methodology.published_at
            )

    async def publish_template_version(
        self, request: PublishTemplateVersion
    ) -> PublishedTemplateVersion:
        self._validate_uuid("template_id", request.template_id)
        self._validate_uuid("template_version_id", request.template_version_id)
        self._validate_now(request.now)
        async with self._session.begin_nested():
            template = await self._lock_template(request.template_id)
            version = (
                await self._session.execute(
                    select(AssessmentTemplateVersion)
                    .where(AssessmentTemplateVersion.id == request.template_version_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                version is None
                or version.template_id != template.id
                or version.status != "draft"
            ):
                raise AssessmentTemplatePublicationInvalid(
                    "template version is not a publishable draft"
                )
            methodology = await self._published_methodology(version.methodology_id)
            if template.source_library_version_id is not None:
                await self._validate_company_source(template, version, methodology)
            await self._validate_structure(version.id)
            version.status = "published"
            version.published_at = request.now
            version.updated_at = request.now
            await self._session.flush()
            return PublishedTemplateVersion(
                template.id,
                version.id,
                version.version,
                version.status,
                version.published_at,
            )

    async def adopt_library_template(
        self, request: AdoptLibraryTemplate
    ) -> AdoptedLibraryTemplate:
        self._validate_uuid("company_id", request.company_id)
        self._validate_uuid(
            "source_library_version_id", request.source_library_version_id
        )
        self._validate_now(request.now)
        code = self._validate_slug(request.company_template_code)
        if request.company_template_name is not None and not isinstance(
            request.company_template_name, str
        ):
            raise InvalidAssessmentTemplateRequest(
                "company_template_name must be a string"
            )
        if request.local_description is not None and not isinstance(
            request.local_description, str
        ):
            raise InvalidAssessmentTemplateRequest("local_description must be a string")
        try:
            async with self._session.begin_nested():
                company = (
                    await self._session.execute(
                        select(Company)
                        .where(Company.id == request.company_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if (
                    company is None
                    or company.deleted_at is not None
                    or company.status != "active"
                ):
                    raise AssessmentTemplateSourceInvalid("company is unavailable")
                source = (
                    await self._session.execute(
                        select(AssessmentTemplateVersion)
                        .where(
                            AssessmentTemplateVersion.id
                            == request.source_library_version_id
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if source is None or source.status != "published":
                    raise AssessmentTemplateSourceInvalid(
                        "library source is unavailable"
                    )
                library = await self._lock_library_source_template(source.template_id)
                methodology = await self._published_methodology(source.methodology_id)
                if methodology.owner_type != "system":
                    raise AssessmentTemplateSourceInvalid(
                        "library methodology is not system-owned"
                    )
                name = (
                    request.company_template_name.strip()
                    if request.company_template_name is not None
                    else library.name
                )
                if not name:
                    raise InvalidAssessmentTemplateRequest(
                        "company template name cannot be empty"
                    )
                new_template = AssessmentTemplate(
                    id=uuid4(),
                    scope="company",
                    company_id=company.id,
                    source_library_version_id=source.id,
                    code=code,
                    name=name,
                    activity_type=library.activity_type,
                    status="active",
                    created_at=request.now,
                    updated_at=request.now,
                )
                draft = AssessmentTemplateVersion(
                    id=uuid4(),
                    template_id=new_template.id,
                    version=1,
                    status="draft",
                    methodology_id=source.methodology_id,
                    local_description=(
                        request.local_description
                        if request.local_description is not None
                        else source.local_description
                    ),
                    change_note=None,
                    published_at=None,
                    created_at=request.now,
                    updated_at=request.now,
                )
                self._session.add_all([new_template, draft])
                await self._session.flush()
                counts = await self._clone_structure(source.id, draft.id, request.now)
                await self._session.flush()
                return AdoptedLibraryTemplate(
                    new_template.id,
                    draft.id,
                    source.id,
                    source.methodology_id,
                    *counts,
                )
        except IntegrityError as error:
            constraint = _postgres_constraint_name(error)
            if constraint == "uq_assessment_templates_active_company_code":
                raise AssessmentTemplateCodeConflict(
                    "active company template code already exists"
                ) from error
            raise

    async def create_next_draft(self, request: CreateNextDraft) -> CreatedTemplateDraft:
        self._validate_uuid("template_id", request.template_id)
        self._validate_uuid(
            "source_published_version_id", request.source_published_version_id
        )
        self._validate_now(request.now)
        if request.change_note is not None and not isinstance(request.change_note, str):
            raise InvalidAssessmentTemplateRequest("change_note must be a string")
        try:
            async with self._session.begin_nested():
                template = await self._lock_template(request.template_id)
                versions = (
                    (
                        await self._session.execute(
                            select(AssessmentTemplateVersion)
                            .where(AssessmentTemplateVersion.template_id == template.id)
                            .order_by(AssessmentTemplateVersion.version)
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
                if any(version.status == "draft" for version in versions):
                    raise AssessmentTemplateDraftExists(
                        "template already has a draft version"
                    )
                published = [
                    version for version in versions if version.status == "published"
                ]
                source = next(
                    (
                        version
                        for version in published
                        if version.id == request.source_published_version_id
                    ),
                    None,
                )
                if source is None or source.version != max(
                    (version.version for version in published), default=0
                ):
                    raise AssessmentTemplateSourceInvalid(
                        "source must be the latest published version"
                    )
                draft = AssessmentTemplateVersion(
                    id=uuid4(),
                    template_id=template.id,
                    version=max(version.version for version in versions) + 1,
                    status="draft",
                    methodology_id=source.methodology_id,
                    local_description=source.local_description,
                    change_note=request.change_note,
                    published_at=None,
                    created_at=request.now,
                    updated_at=request.now,
                )
                self._session.add(draft)
                await self._session.flush()
                counts = await self._clone_structure(source.id, draft.id, request.now)
                await self._session.flush()
                return CreatedTemplateDraft(
                    template.id, draft.id, draft.version, *counts
                )
        except IntegrityError as error:
            constraint = _postgres_constraint_name(error)
            if constraint == "uq_assessment_template_versions_template_version":
                raise AssessmentTemplateVersionConflict(
                    "next template version was created concurrently"
                ) from error
            raise

    async def assert_editable_draft(
        self, template_id: UUID, template_version_id: UUID
    ) -> None:
        self._validate_uuid("template_id", template_id)
        self._validate_uuid("template_version_id", template_version_id)
        template = await self._lock_template(template_id)
        version = (
            await self._session.execute(
                select(AssessmentTemplateVersion).where(
                    AssessmentTemplateVersion.id == template_version_id
                )
            )
        ).scalar_one_or_none()
        if (
            version is None
            or version.template_id != template.id
            or version.status != "draft"
        ):
            raise AssessmentTemplateNotEditable(
                "template version is not an editable draft"
            )

    async def _lock_template(self, template_id: UUID) -> AssessmentTemplate:
        template = (
            await self._session.execute(
                select(AssessmentTemplate)
                .where(AssessmentTemplate.id == template_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            template is None
            or template.deleted_at is not None
            or template.status != "active"
        ):
            raise AssessmentTemplateNotFound("template is unavailable")
        return template

    async def _lock_library_source_template(
        self, template_id: UUID
    ) -> AssessmentTemplate:
        template = (
            await self._session.execute(
                select(AssessmentTemplate)
                .where(AssessmentTemplate.id == template_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if template is None:
            raise AssessmentTemplateNotFound("source template is unavailable")
        if (
            template.scope != "library"
            or template.status != "active"
            or template.deleted_at is not None
        ):
            raise AssessmentTemplateSourceInvalid(
                "source template is not eligible for adoption"
            )
        return template

    async def _published_methodology(
        self, methodology_id: UUID
    ) -> AssessmentMethodology:
        methodology = (
            await self._session.execute(
                select(AssessmentMethodology).where(
                    AssessmentMethodology.id == methodology_id
                )
            )
        ).scalar_one_or_none()
        if (
            methodology is None
            or methodology.deleted_at is not None
            or methodology.status != "published"
        ):
            raise AssessmentTemplatePublicationInvalid("methodology is not published")
        return methodology

    async def _validate_company_source(
        self,
        template: AssessmentTemplate,
        version: AssessmentTemplateVersion,
        methodology: AssessmentMethodology,
    ) -> None:
        source = (
            await self._session.execute(
                select(AssessmentTemplateVersion).where(
                    AssessmentTemplateVersion.id == template.source_library_version_id
                )
            )
        ).scalar_one_or_none()
        if (
            source is None
            or source.status != "published"
            or source.methodology_id != methodology.id
        ):
            raise AssessmentTemplateSourceInvalid(
                "company template provenance is invalid"
            )
        library = (
            await self._session.execute(
                select(AssessmentTemplate).where(
                    AssessmentTemplate.id == source.template_id
                )
            )
        ).scalar_one_or_none()
        if (
            library is None
            or library.scope != "library"
            or library.status != "active"
            or library.deleted_at is not None
        ):
            raise AssessmentTemplateSourceInvalid(
                "library template provenance is invalid"
            )

    async def _validate_structure(self, version_id: UUID) -> None:
        sections = (
            (
                await self._session.execute(
                    select(AssessmentTemplateSection).where(
                        AssessmentTemplateSection.template_version_id == version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        items = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItem).where(
                        AssessmentTemplateItem.template_version_id == version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if not sections or not items:
            raise AssessmentTemplatePublicationInvalid(
                "template structure requires sections and items"
            )
        section_ids = {section.id for section in sections}
        parents = {section.id: section.parent_section_id for section in sections}
        for section in sections:
            if (
                not self._nonempty_slug(section.code)
                or not self._nonempty(section.title)
                or section.sort_order < 0
                or (section.weight is not None and section.weight < 0)
                or (
                    section.parent_section_id is not None
                    and section.parent_section_id not in section_ids
                )
            ):
                raise AssessmentTemplatePublicationInvalid(
                    "section structure is invalid"
                )
            seen: set[UUID] = set()
            current: UUID | None = section.id
            while current is not None:
                if current in seen:
                    raise AssessmentTemplatePublicationInvalid(
                        "section hierarchy contains a cycle"
                    )
                seen.add(current)
                current = parents.get(current)
        options = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItemOption).where(
                        AssessmentTemplateItemOption.item_id.in_(
                            [item.id for item in items]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        by_item: dict[UUID, list[AssessmentTemplateItemOption]] = {}
        for option in options:
            by_item.setdefault(option.item_id, []).append(option)
            if (
                not self._nonempty_slug(option.code)
                or not self._nonempty(option.label)
                or option.sort_order < 0
            ):
                raise AssessmentTemplatePublicationInvalid("item option is invalid")
        for item in items:
            item_options = by_item.get(item.id, [])
            if (
                item.section_id not in section_ids
                or not self._nonempty_slug(item.code)
                or not self._nonempty(item.prompt)
                or item.sort_order < 0
                or (item.weight is not None and item.weight < 0)
                or not isinstance(item.config, dict)
                or (
                    item.min_value is not None
                    and item.max_value is not None
                    and item.min_value > item.max_value
                )
                or (
                    item.passing_value is not None
                    and (
                        (
                            item.min_value is not None
                            and item.passing_value < item.min_value
                        )
                        or (
                            item.max_value is not None
                            and item.passing_value > item.max_value
                        )
                    )
                )
                or (item.response_type in _CHOICE_TYPES and len(item_options) < 2)
                or (item.response_type not in _CHOICE_TYPES and item_options)
            ):
                raise AssessmentTemplatePublicationInvalid("item structure is invalid")
        policy = await self._session.get(AssessmentScoringPolicy, version_id)
        if policy is not None:
            if policy.algorithm != "weighted_v1" or policy.version != 1:
                raise AssessmentTemplatePublicationInvalid(
                    "weighted scoring policy is invalid"
                )
            for item in items:
                if (
                    item.response_type not in _WEIGHTED_TYPES
                    or item.weight is None
                    or item.weight <= 0
                    or (
                        item.response_type
                        in {"score", "integer", "decimal", "single_choice"}
                        and (
                            item.min_value is None
                            or item.max_value is None
                            or item.max_value <= item.min_value
                        )
                    )
                ):
                    raise AssessmentTemplatePublicationInvalid(
                        "weighted item configuration is incomplete"
                    )
                if item.response_type == "single_choice" and any(
                    option.numeric_value is None for option in by_item.get(item.id, [])
                ):
                    raise AssessmentTemplatePublicationInvalid(
                        "weighted choice options require numeric values"
                    )
            mapping_rows = (
                await self._session.execute(
                    select(AssessmentItemMetricMapping, AssessmentMetricDefinition)
                    .join(
                        AssessmentMetricDefinition,
                        AssessmentMetricDefinition.id
                        == AssessmentItemMetricMapping.metric_definition_id,
                    )
                    .where(
                        AssessmentItemMetricMapping.template_version_id == version_id
                    )
                )
            ).all()
            mapped_items = {mapping.item_id for mapping, _ in mapping_rows}
            if mapped_items != {item.id for item in items} or any(
                definition.status != "active"
                or definition.code not in _CANONICAL_METRICS
                or mapping.contribution_weight is None
                or mapping.contribution_weight <= 0
                for mapping, definition in mapping_rows
            ):
                raise AssessmentTemplatePublicationInvalid(
                    "weighted metric mapping is incomplete"
                )

    async def _clone_structure(
        self, source_version_id: UUID, target_version_id: UUID, now: datetime
    ) -> tuple[int, int, int]:
        sections = (
            (
                await self._session.execute(
                    select(AssessmentTemplateSection)
                    .where(
                        AssessmentTemplateSection.template_version_id
                        == source_version_id
                    )
                    .order_by(AssessmentTemplateSection.sort_order)
                )
            )
            .scalars()
            .all()
        )
        section_map = {section.id: uuid4() for section in sections}
        pending = list(sections)
        while pending:
            ready = [
                section
                for section in pending
                if section.parent_section_id is None
                or section.parent_section_id not in {value.id for value in pending}
            ]
            if not ready:
                raise AssessmentTemplateSourceInvalid(
                    "source section hierarchy contains a cycle"
                )
            for section in ready:
                self._session.add(
                    AssessmentTemplateSection(
                        id=section_map[section.id],
                        template_version_id=target_version_id,
                        parent_section_id=(
                            section_map[section.parent_section_id]
                            if section.parent_section_id
                            else None
                        ),
                        code=section.code,
                        title=section.title,
                        description=section.description,
                        section_kind=section.section_kind,
                        sort_order=section.sort_order,
                        weight=section.weight,
                        created_at=now,
                        updated_at=now,
                    )
                )
                pending.remove(section)
            await self._session.flush()
        items = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItem)
                    .where(
                        AssessmentTemplateItem.template_version_id == source_version_id
                    )
                    .order_by(AssessmentTemplateItem.sort_order)
                )
            )
            .scalars()
            .all()
        )
        item_map = {item.id: uuid4() for item in items}
        self._session.add_all(
            [
                AssessmentTemplateItem(
                    id=item_map[item.id],
                    template_version_id=target_version_id,
                    section_id=section_map[item.section_id],
                    code=item.code,
                    prompt=item.prompt,
                    guidance=item.guidance,
                    response_type=item.response_type,
                    is_required=item.is_required,
                    sort_order=item.sort_order,
                    weight=item.weight,
                    min_value=item.min_value,
                    max_value=item.max_value,
                    passing_value=item.passing_value,
                    evidence_mode=item.evidence_mode,
                    criticality=item.criticality,
                    config=deepcopy(item.config),
                    created_at=now,
                    updated_at=now,
                )
                for item in items
            ]
        )
        await self._session.flush()
        options = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItemOption).where(
                        AssessmentTemplateItemOption.item_id.in_(list(item_map))
                    )
                )
            )
            .scalars()
            .all()
        )
        self._session.add_all(
            [
                AssessmentTemplateItemOption(
                    id=uuid4(),
                    item_id=item_map[option.item_id],
                    code=option.code,
                    label=option.label,
                    sort_order=option.sort_order,
                    numeric_value=option.numeric_value,
                    is_disqualifying=option.is_disqualifying,
                    created_at=now,
                    updated_at=now,
                )
                for option in options
            ]
        )
        policy = await self._session.get(AssessmentScoringPolicy, source_version_id)
        if policy is not None:
            self._session.add(
                AssessmentScoringPolicy(
                    template_version_id=target_version_id,
                    algorithm=policy.algorithm,
                    version=policy.version,
                    config=deepcopy(policy.config),
                    created_at=now,
                    updated_at=now,
                )
            )
            mappings = (
                (
                    await self._session.execute(
                        select(AssessmentItemMetricMapping).where(
                            AssessmentItemMetricMapping.template_version_id
                            == source_version_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            self._session.add_all(
                [
                    AssessmentItemMetricMapping(
                        template_version_id=target_version_id,
                        item_id=item_map[mapping.item_id],
                        metric_definition_id=mapping.metric_definition_id,
                        contribution_weight=mapping.contribution_weight,
                        direction=mapping.direction,
                        created_at=now,
                        updated_at=now,
                    )
                    for mapping in mappings
                ]
            )
        return len(sections), len(items), len(options)

    @staticmethod
    def _validate_uuid(name: str, value: object) -> None:
        if not isinstance(value, UUID):
            raise InvalidAssessmentTemplateRequest(f"{name} must be a UUID")

    @staticmethod
    def _validate_now(value: object) -> None:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise InvalidAssessmentTemplateRequest(
                "now must be a timezone-aware datetime"
            )

    @staticmethod
    def _validate_slug(value: object) -> str:
        if not isinstance(value, str):
            raise InvalidAssessmentTemplateRequest("code must be a string")
        normalized = value.strip().lower()
        if not _SLUG.fullmatch(normalized):
            raise InvalidAssessmentTemplateRequest("code must be a safe slug")
        return normalized

    @staticmethod
    def _nonempty(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @classmethod
    def _nonempty_slug(cls, value: object) -> bool:
        return cls._nonempty(value) and bool(_SLUG.fullmatch(value.strip().lower()))


def _postgres_constraint_name(error: IntegrityError) -> str | None:
    """Extract a PostgreSQL constraint name without parsing error text."""

    current: object | None = error.orig
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        diagnostic = getattr(current, "diag", None)
        name = getattr(diagnostic, "constraint_name", None)
        if isinstance(name, str):
            return name
        name = getattr(current, "constraint_name", None)
        if isinstance(name, str):
            return name
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )
    return None
