"""Atomic document-style editing for assessment template drafts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import json
import math
import re
from uuid import UUID, uuid4

from sqlalchemy import delete, select
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
)


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SECTION_KINDS = {"section", "zone", "group"}
_RESPONSE_TYPES = {
    "boolean", "score", "integer", "decimal", "text",
    "single_choice", "multi_choice", "date", "time",
}
_EVIDENCE_MODES = {
    "none", "optional_photo", "required_photo", "optional_comment",
    "required_comment", "photo_and_comment",
}
_CRITICALITIES = {"normal", "critical", "stop_factor"}
_CHOICES = {"single_choice", "multi_choice"}
_METRIC_DIRECTIONS = {"positive", "inverse"}
_CANONICAL_METRIC_CODES = {
    "people", "service", "taste", "speed", "order", "space", "economics",
}


class AssessmentDraftError(Exception):
    pass


class InvalidAssessmentDraftRequest(AssessmentDraftError):
    pass


class AssessmentDraftNotFound(AssessmentDraftError):
    pass


class AssessmentDraftNotEditable(AssessmentDraftError):
    pass


class AssessmentDraftRevisionConflict(AssessmentDraftError):
    pass


class AssessmentDraftStructureInvalid(AssessmentDraftError):
    pass


@dataclass(frozen=True)
class DraftOptionInput:
    code: str
    label: str
    sort_order: int
    numeric_value: Decimal | None
    is_disqualifying: bool


@dataclass(frozen=True)
class DraftMetricMappingInput:
    metric_code: str
    contribution_weight: Decimal
    direction: str


@dataclass(frozen=True)
class DraftItemInput:
    code: str
    prompt: str
    guidance: str | None
    response_type: str
    is_required: bool
    sort_order: int
    weight: Decimal | None
    min_value: Decimal | None
    max_value: Decimal | None
    passing_value: Decimal | None
    evidence_mode: str
    criticality: str
    config: dict
    options: list[DraftOptionInput]
    metric_mappings: list[DraftMetricMappingInput] = field(default_factory=list)


@dataclass(frozen=True)
class DraftSectionInput:
    code: str
    title: str
    description: str | None
    section_kind: str
    sort_order: int
    weight: Decimal | None
    parent_code: str | None
    items: list[DraftItemInput]


@dataclass(frozen=True)
class SaveDraftDocument:
    template_id: UUID
    template_version_id: UUID
    expected_edit_revision: int
    sections: list[DraftSectionInput]
    now: datetime
    template_name: str | None = None
    local_description: str | None = None
    change_note: str | None = None


@dataclass(frozen=True)
class GetDraftDocument:
    template_id: UUID
    template_version_id: UUID


@dataclass(frozen=True)
class SavedDraftDocument:
    template_id: UUID
    template_version_id: UUID
    previous_edit_revision: int
    edit_revision: int
    section_count: int
    item_count: int
    option_count: int
    updated_at: datetime


@dataclass(frozen=True)
class DraftDocument:
    template: dict
    version: dict
    methodology: dict
    sections: list[dict]


class AssessmentDraftService:
    """Replace a complete draft document without owning the outer transaction."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_draft_document(self, request: GetDraftDocument) -> DraftDocument:
        self._uuid(request.template_id)
        self._uuid(request.template_version_id)
        template, version = await self._load_editable(
            request.template_id, request.template_version_id, lock=False
        )
        methodology = await self._session.get(
            AssessmentMethodology, version.methodology_id
        )
        if methodology is None:
            raise AssessmentDraftNotFound("methodology is unavailable")
        sections = (
            await self._session.execute(
                select(AssessmentTemplateSection)
                .where(AssessmentTemplateSection.template_version_id == version.id)
                .order_by(
                    AssessmentTemplateSection.sort_order,
                    AssessmentTemplateSection.code,
                    AssessmentTemplateSection.id,
                )
            )
        ).scalars().all()
        items = (
            await self._session.execute(
                select(AssessmentTemplateItem)
                .where(AssessmentTemplateItem.template_version_id == version.id)
                .order_by(
                    AssessmentTemplateItem.sort_order,
                    AssessmentTemplateItem.code,
                    AssessmentTemplateItem.id,
                )
            )
        ).scalars().all()
        options = (
            await self._session.execute(
                select(AssessmentTemplateItemOption)
                .where(
                    AssessmentTemplateItemOption.item_id.in_(
                        [item.id for item in items]
                    )
                )
                .order_by(
                    AssessmentTemplateItemOption.sort_order,
                    AssessmentTemplateItemOption.code,
                    AssessmentTemplateItemOption.id,
                )
            )
        ).scalars().all() if items else []
        mappings = (
            await self._session.execute(
                select(AssessmentItemMetricMapping, AssessmentMetricDefinition.code)
                .join(
                    AssessmentMetricDefinition,
                    AssessmentMetricDefinition.id
                    == AssessmentItemMetricMapping.metric_definition_id,
                )
                .where(
                    AssessmentItemMetricMapping.template_version_id == version.id
                )
                .order_by(
                    AssessmentItemMetricMapping.item_id,
                    AssessmentMetricDefinition.code,
                )
            )
        ).all() if items else []
        section_codes = {section.id: section.code for section in sections}
        item_options: dict[UUID, list[dict]] = {}
        for option in options:
            item_options.setdefault(option.item_id, []).append(
                self._row(option, exclude={"item_id"})
            )
        item_mappings: dict[UUID, list[dict]] = {}
        for mapping, metric_code in mappings:
            item_mappings.setdefault(mapping.item_id, []).append({
                "metric_code": metric_code,
                "contribution_weight": mapping.contribution_weight,
                "direction": mapping.direction,
            })
        section_items: dict[UUID, list[dict]] = {}
        for item in items:
            value = self._row(item, exclude={"template_version_id", "section_id"})
            value["config"] = deepcopy(item.config)
            value["options"] = item_options.get(item.id, [])
            value["metric_mappings"] = item_mappings.get(item.id, [])
            section_items.setdefault(item.section_id, []).append(value)
        result_sections = []
        for section in sections:
            value = self._row(
                section, exclude={"template_version_id", "parent_section_id"}
            )
            value["parent_code"] = section_codes.get(section.parent_section_id)
            value["items"] = section_items.get(section.id, [])
            result_sections.append(value)
        return DraftDocument(
            template={
                "id": template.id,
                "scope": template.scope,
                "company_id": template.company_id,
                "source_library_version_id": template.source_library_version_id,
                "name": template.name,
                "code": template.code,
                "activity_type": template.activity_type,
            },
            version={
                "id": version.id,
                "version": version.version,
                "status": version.status,
                "edit_revision": version.edit_revision,
                "local_description": version.local_description,
            },
            methodology={
                "id": methodology.id,
                "title": methodology.title,
                "body": methodology.body,
                "version": methodology.version,
                "owner_type": methodology.owner_type,
            },
            sections=result_sections,
        )

    async def save_draft_document(
        self, request: SaveDraftDocument
    ) -> SavedDraftDocument:
        normalized = self._validate(request)
        async with self._session.begin_nested():
            template, version = await self._load_editable(
                request.template_id, request.template_version_id, lock=True
            )
            if version.edit_revision != request.expected_edit_revision:
                raise AssessmentDraftRevisionConflict("draft revision is stale")
            previous = version.edit_revision
            metric_definitions = await self._active_metric_definitions(normalized)
            item_ids = select(AssessmentTemplateItem.id).where(
                AssessmentTemplateItem.template_version_id == version.id
            )
            await self._session.execute(
                delete(AssessmentItemMetricMapping).where(
                    AssessmentItemMetricMapping.template_version_id == version.id
                )
            )
            await self._session.execute(
                delete(AssessmentTemplateItemOption).where(
                    AssessmentTemplateItemOption.item_id.in_(item_ids)
                )
            )
            await self._session.execute(
                delete(AssessmentTemplateItem).where(
                    AssessmentTemplateItem.template_version_id == version.id
                )
            )
            await self._session.execute(
                delete(AssessmentTemplateSection).where(
                    AssessmentTemplateSection.template_version_id == version.id
                )
            )
            await self._session.flush()
            section_ids = {section["code"]: uuid4() for section in normalized}
            pending = list(normalized)
            while pending:
                ready = [
                    value for value in pending
                    if value["parent_code"] is None
                    or value["parent_code"] not in {row["code"] for row in pending}
                ]
                if not ready:
                    raise AssessmentDraftStructureInvalid(
                        "section hierarchy contains a cycle"
                    )
                self._session.add_all(
                    [
                        AssessmentTemplateSection(
                            id=section_ids[value["code"]],
                            template_version_id=version.id,
                            parent_section_id=section_ids.get(value["parent_code"]),
                            code=value["code"],
                            title=value["title"],
                            description=value["description"],
                            section_kind=value["section_kind"],
                            sort_order=value["sort_order"],
                            weight=value["weight"],
                            created_at=request.now,
                            updated_at=request.now,
                        )
                        for value in ready
                    ]
                )
                for value in ready:
                    pending.remove(value)
                await self._session.flush()
            item_count = option_count = 0
            for section in normalized:
                for item in section["items"]:
                    item_id = uuid4()
                    self._session.add(
                        AssessmentTemplateItem(
                            id=item_id,
                            template_version_id=version.id,
                            section_id=section_ids[section["code"]],
                            created_at=request.now,
                            updated_at=request.now,
                            **{
                                key: value for key, value in item.items()
                                if key not in {"options", "metric_mappings"}
                            },
                        )
                    )
                    await self._session.flush()
                    self._session.add_all(
                        [
                            AssessmentTemplateItemOption(
                                id=uuid4(),
                                item_id=item_id,
                                created_at=request.now,
                                updated_at=request.now,
                                **option,
                            )
                            for option in item["options"]
                        ]
                    )
                    self._session.add_all(
                        [
                            AssessmentItemMetricMapping(
                                id=uuid4(),
                                template_version_id=version.id,
                                item_id=item_id,
                                metric_definition_id=metric_definitions[
                                    mapping["metric_code"]
                                ].id,
                                contribution_weight=mapping["contribution_weight"],
                                direction=mapping["direction"],
                                created_at=request.now,
                                updated_at=request.now,
                            )
                            for mapping in item["metric_mappings"]
                        ]
                    )
                    item_count += 1
                    option_count += len(item["options"])
            if request.template_name is not None:
                template.name = request.template_name.strip()
                template.updated_at = request.now
            version.local_description = self._nullable(request.local_description)
            version.change_note = self._nullable(request.change_note)
            version.edit_revision += 1
            version.updated_at = request.now
            await self._session.flush()
            return SavedDraftDocument(
                template.id, version.id, previous, version.edit_revision,
                len(normalized), item_count, option_count, request.now,
            )

    async def _active_metric_definitions(self, sections: list[dict]):
        requested = {
            mapping["metric_code"]
            for section in sections
            for item in section["items"]
            for mapping in item["metric_mappings"]
        }
        if not requested:
            return {}
        definitions = (
            await self._session.execute(
                select(AssessmentMetricDefinition).where(
                    AssessmentMetricDefinition.code.in_(requested),
                    AssessmentMetricDefinition.status == "active",
                )
            )
        ).scalars().all()
        result = {definition.code: definition for definition in definitions}
        if set(result) != requested:
            raise AssessmentDraftStructureInvalid(
                "metric mapping references an unavailable metric"
            )
        return result

    async def _load_editable(self, template_id, version_id, *, lock):
        template_query = select(AssessmentTemplate).where(
            AssessmentTemplate.id == template_id
        )
        if lock:
            template_query = template_query.with_for_update()
        template = (await self._session.execute(template_query)).scalar_one_or_none()
        if template is None:
            raise AssessmentDraftNotFound("template is unavailable")
        if template.status != "active" or template.deleted_at is not None:
            raise AssessmentDraftNotEditable("template is not editable")
        version_query = select(AssessmentTemplateVersion).where(
            AssessmentTemplateVersion.id == version_id
        )
        if lock:
            version_query = version_query.with_for_update()
        version = (await self._session.execute(version_query)).scalar_one_or_none()
        if version is None or version.template_id != template.id:
            raise AssessmentDraftNotFound("template version is unavailable")
        if version.status != "draft":
            raise AssessmentDraftNotEditable("template version is not a draft")
        return template, version

    def _validate(self, request: SaveDraftDocument) -> list[dict]:
        self._uuid(request.template_id)
        self._uuid(request.template_version_id)
        if (
            not isinstance(request.expected_edit_revision, int)
            or isinstance(request.expected_edit_revision, bool)
            or request.expected_edit_revision < 1
        ):
            raise InvalidAssessmentDraftRequest("edit revision is invalid")
        if (
            not isinstance(request.now, datetime)
            or request.now.tzinfo is None
            or request.now.utcoffset() is None
        ):
            raise InvalidAssessmentDraftRequest("now must be timezone-aware")
        if not isinstance(request.sections, list):
            raise InvalidAssessmentDraftRequest("sections must be a list")
        for value in (
            request.template_name, request.local_description, request.change_note
        ):
            if value is not None and not isinstance(value, str):
                raise InvalidAssessmentDraftRequest("text value has invalid type")
        sections, section_codes, item_codes = [], set(), set()
        for source in request.sections:
            if not isinstance(source, DraftSectionInput):
                raise InvalidAssessmentDraftRequest("section has invalid type")
            code = self._slug(source.code)
            if code in section_codes:
                raise AssessmentDraftStructureInvalid("duplicate section code")
            section_codes.add(code)
            self._integer(source.sort_order)
            self._numeric(source.weight)
            if source.section_kind not in _SECTION_KINDS:
                raise InvalidAssessmentDraftRequest("section kind is invalid")
            if not isinstance(source.items, list):
                raise InvalidAssessmentDraftRequest("items must be a list")
            items = []
            for item in source.items:
                if not isinstance(item, DraftItemInput):
                    raise InvalidAssessmentDraftRequest("item has invalid type")
                item_code = self._slug(item.code)
                if item_code in item_codes:
                    raise AssessmentDraftStructureInvalid("duplicate item code")
                item_codes.add(item_code)
                self._integer(item.sort_order)
                for number in (item.weight, item.min_value, item.max_value, item.passing_value):
                    self._numeric(number)
                if item.response_type not in _RESPONSE_TYPES:
                    raise InvalidAssessmentDraftRequest("response type is invalid")
                if item.evidence_mode not in _EVIDENCE_MODES or item.criticality not in _CRITICALITIES:
                    raise InvalidAssessmentDraftRequest("item enum is invalid")
                if not isinstance(item.is_required, bool) or not isinstance(item.config, dict):
                    raise InvalidAssessmentDraftRequest("item value has invalid type")
                self._json(item.config)
                if item.min_value is not None and item.max_value is not None and item.min_value > item.max_value:
                    raise AssessmentDraftStructureInvalid("numeric range is invalid")
                if item.passing_value is not None and (
                    (item.min_value is not None and item.passing_value < item.min_value)
                    or (item.max_value is not None and item.passing_value > item.max_value)
                ):
                    raise AssessmentDraftStructureInvalid("passing value is invalid")
                if not isinstance(item.options, list):
                    raise InvalidAssessmentDraftRequest("options must be a list")
                if item.response_type not in _CHOICES and item.options:
                    raise AssessmentDraftStructureInvalid("options are not allowed")
                option_codes, options = set(), []
                for option in item.options:
                    if not isinstance(option, DraftOptionInput):
                        raise InvalidAssessmentDraftRequest("option has invalid type")
                    option_code = self._slug(option.code)
                    if option_code in option_codes:
                        raise AssessmentDraftStructureInvalid("duplicate option code")
                    option_codes.add(option_code)
                    self._integer(option.sort_order)
                    self._numeric(option.numeric_value)
                    if not isinstance(option.is_disqualifying, bool):
                        raise InvalidAssessmentDraftRequest("option value has invalid type")
                    options.append({
                        "code": option_code, "label": option.label.strip(),
                        "sort_order": option.sort_order,
                        "numeric_value": option.numeric_value,
                        "is_disqualifying": option.is_disqualifying,
                    })
                if not isinstance(item.metric_mappings, list):
                    raise InvalidAssessmentDraftRequest(
                        "metric mappings must be a list"
                    )
                metric_codes, metric_mappings = set(), []
                for mapping in item.metric_mappings:
                    if not isinstance(mapping, DraftMetricMappingInput):
                        raise InvalidAssessmentDraftRequest(
                            "metric mapping has invalid type"
                        )
                    if mapping.metric_code not in _CANONICAL_METRIC_CODES:
                        raise AssessmentDraftStructureInvalid(
                            "metric mapping is not canonical"
                        )
                    if mapping.metric_code in metric_codes:
                        raise AssessmentDraftStructureInvalid(
                            "duplicate metric mapping"
                        )
                    metric_codes.add(mapping.metric_code)
                    if mapping.direction not in _METRIC_DIRECTIONS:
                        raise InvalidAssessmentDraftRequest(
                            "metric mapping direction is invalid"
                        )
                    self._positive_numeric(mapping.contribution_weight)
                    metric_mappings.append({
                        "metric_code": mapping.metric_code,
                        "contribution_weight": (
                            item.weight
                            if item.weight is not None
                            else mapping.contribution_weight
                        ),
                        "direction": mapping.direction,
                    })
                items.append({
                    "code": item_code, "prompt": item.prompt.strip(),
                    "guidance": self._nullable(item.guidance),
                    "response_type": item.response_type,
                    "is_required": item.is_required, "sort_order": item.sort_order,
                    "weight": item.weight, "min_value": item.min_value,
                    "max_value": item.max_value,
                    "passing_value": item.passing_value,
                    "evidence_mode": item.evidence_mode,
                    "criticality": item.criticality,
                    "config": deepcopy(item.config), "options": options,
                    "metric_mappings": metric_mappings,
                })
            parent = self._slug(source.parent_code) if source.parent_code else None
            if parent == code:
                raise AssessmentDraftStructureInvalid("section cannot parent itself")
            sections.append({
                "code": code, "title": source.title.strip(),
                "description": self._nullable(source.description),
                "section_kind": source.section_kind,
                "sort_order": source.sort_order, "weight": source.weight,
                "parent_code": parent, "items": items,
            })
        for section in sections:
            if section["parent_code"] and section["parent_code"] not in section_codes:
                raise AssessmentDraftStructureInvalid("parent section is missing")
        return sections

    @staticmethod
    def _uuid(value):
        if not isinstance(value, UUID):
            raise InvalidAssessmentDraftRequest("identifier must be a UUID")

    @staticmethod
    def _slug(value):
        if not isinstance(value, str):
            raise InvalidAssessmentDraftRequest("code must be a string")
        value = value.strip().lower()
        if not _SLUG.fullmatch(value):
            raise InvalidAssessmentDraftRequest("code must be a safe slug")
        return value

    @staticmethod
    def _integer(value):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise InvalidAssessmentDraftRequest("order must be a non-negative integer")

    @staticmethod
    def _numeric(value):
        if value is not None and (
            not isinstance(value, (int, Decimal))
            or isinstance(value, bool)
            or value < 0
        ):
            raise InvalidAssessmentDraftRequest("numeric value is invalid")

    @staticmethod
    def _positive_numeric(value):
        if (
            not isinstance(value, (int, Decimal))
            or isinstance(value, bool)
            or value <= 0
        ):
            raise InvalidAssessmentDraftRequest(
                "metric contribution weight must be positive"
            )

    @staticmethod
    def _nullable(value):
        if value is None:
            return None
        return value.strip() or None

    @staticmethod
    def _json(value):
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError):
            raise InvalidAssessmentDraftRequest("config must be finite JSON") from None

    @staticmethod
    def _row(value, *, exclude):
        return {
            column.name: getattr(value, column.name)
            for column in value.__table__.columns
            if column.name not in exclude
        }
