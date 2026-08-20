"""Strict idempotent importers for reviewed template manifests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models import (
    AssessmentItemMetricMapping,
    AssessmentMethodology,
    AssessmentMetricDefinition,
    AssessmentScoringPolicy,
    AssessmentTemplate,
    AssessmentTemplateImportSource,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
    Company,
)


_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_ACTIVITY_TYPES = {
    "evaluation",
    "measurement",
    "walkthrough",
    "checklist",
    "test",
    "survey",
    "attestation",
}
_METRICS = {
    "taste": "Вкус",
    "speed": "Скорость",
    "order": "Порядок",
    "service": "Сервис",
    "people": "Люди",
    "space": "Пространство",
    "economics": "Экономика",
    "food_safety": "Пищевая безопасность",
}
MAX_SECTIONS = 500
MAX_ITEMS = 5_000
MAX_OPTIONS = 100


class AssessmentTemplateImportError(Exception):
    pass


class AssessmentTemplateImportConflict(AssessmentTemplateImportError):
    pass


@dataclass(frozen=True)
class ImportPlan:
    action: str
    template_code: str
    next_version: int | None
    section_count: int
    item_count: int
    source_filename: str
    source_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class ImportResult:
    action: str
    template_id: UUID
    template_version_id: UUID
    version: int
    section_count: int
    item_count: int
    mapping_count: int


@dataclass(frozen=True)
class ReviewedManifest:
    document: Mapping[str, Any]
    canonical_bytes: bytes
    manifest_sha256: str

    @classmethod
    def parse(cls, raw: bytes) -> "ReviewedManifest":
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AssessmentTemplateImportError("manifest is not valid JSON") from error
        if not isinstance(value, dict):
            raise AssessmentTemplateImportError("manifest root must be an object")
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest = cls(value, canonical, sha256(canonical).hexdigest())
        manifest.validate()
        return manifest

    def publication_ready(self) -> bool:
        """Return true only when every weighted input and contribution is known."""
        items = (
            item
            for section in self.document["template"]["sections"]
            for item in section["items"]
        )
        return all(
            item["weight"] is not None
            and all(mapping["weight"] is not None for mapping in item["metrics"])
            for item in items
        )

    def validate(self) -> None:
        root = self.document
        _exact_keys(
            root,
            {"schema_version", "source", "template"},
            "manifest",
        )
        if root["schema_version"] != 1:
            raise AssessmentTemplateImportError("unsupported manifest schema")
        source = _object(root["source"], "source")
        _exact_keys(source, {"filename", "sha256", "provenance"}, "source")
        if source["provenance"] != "read_only_methodology_source":
            raise AssessmentTemplateImportError("source provenance is invalid")
        if (
            not isinstance(source["filename"], str)
            or not source["filename"].strip()
            or "/" in source["filename"]
            or "\\" in source["filename"]
        ):
            raise AssessmentTemplateImportError("source filename is invalid")
        if not isinstance(source["sha256"], str) or not _SHA.fullmatch(
            source["sha256"]
        ):
            raise AssessmentTemplateImportError("source sha256 is invalid")

        template = _object(root["template"], "template")
        _exact_keys(
            template,
            {
                "code",
                "name",
                "activity_type",
                "description",
                "methodology",
                "scoring",
                "sections",
            },
            "template",
        )
        _slug(template["code"], "template code")
        _bounded_text(template["name"], "template name", 255)
        _bounded_optional_text(template["description"], "description", 10_000)
        if template["activity_type"] not in _ACTIVITY_TYPES:
            raise AssessmentTemplateImportError("activity type is invalid")
        methodology = _object(template["methodology"], "methodology")
        _exact_keys(methodology, {"code", "title", "body", "version"}, "methodology")
        _slug(methodology["code"], "methodology code")
        _bounded_text(methodology["title"], "methodology title", 255)
        _bounded_text(methodology["body"], "methodology body", 20_000)
        if type(methodology["version"]) is not int or methodology["version"] < 1:
            raise AssessmentTemplateImportError("methodology version is invalid")
        scoring = _object(template["scoring"], "scoring")
        _exact_keys(scoring, {"algorithm", "version", "config"}, "scoring")
        if scoring["algorithm"] != "weighted_v1" or scoring["version"] != 1:
            raise AssessmentTemplateImportError("scoring policy is invalid")
        if not isinstance(scoring["config"], dict):
            raise AssessmentTemplateImportError("scoring config is invalid")

        sections = template["sections"]
        if not isinstance(sections, list) or not 1 <= len(sections) <= MAX_SECTIONS:
            raise AssessmentTemplateImportError("section count is invalid")
        section_codes: set[str] = set()
        item_codes: set[str] = set()
        item_count = 0
        for section in sections:
            section = _object(section, "section")
            _exact_keys(
                section,
                {"code", "title", "description", "kind", "weight", "items"},
                "section",
            )
            code = _slug(section["code"], "section code")
            if code in section_codes:
                raise AssessmentTemplateImportError("duplicate section code")
            section_codes.add(code)
            _bounded_text(section["title"], "section title", 255)
            _bounded_optional_text(
                section["description"], "section description", 10_000
            )
            if section["kind"] not in {"section", "zone", "group"}:
                raise AssessmentTemplateImportError("section kind is invalid")
            _optional_positive_decimal(section["weight"], "section weight")
            items = section["items"]
            if not isinstance(items, list) or not items:
                raise AssessmentTemplateImportError("section requires items")
            item_count += len(items)
            if item_count > MAX_ITEMS:
                raise AssessmentTemplateImportError("item count exceeds bound")
            for item in items:
                item = _object(item, "item")
                _exact_keys(
                    item,
                    {
                        "code",
                        "prompt",
                        "guidance",
                        "response_type",
                        "required",
                        "weight",
                        "min_value",
                        "max_value",
                        "passing_value",
                        "evidence_mode",
                        "criticality",
                        "config",
                        "options",
                        "metrics",
                    },
                    "item",
                )
                item_code = _slug(item["code"], "item code")
                if item_code in item_codes:
                    raise AssessmentTemplateImportError("duplicate item code")
                item_codes.add(item_code)
                _bounded_text(item["prompt"], "item prompt", 20_000)
                _bounded_optional_text(item["guidance"], "item guidance", 20_000)
                if item["response_type"] not in {
                    "boolean",
                    "score",
                    "integer",
                    "decimal",
                    "single_choice",
                }:
                    raise AssessmentTemplateImportError(
                        "weighted item response type is unsupported"
                    )
                if type(item["required"]) is not bool:
                    raise AssessmentTemplateImportError("required flag is invalid")
                _optional_positive_decimal(item["weight"], "item weight")
                for name in ("min_value", "max_value", "passing_value"):
                    _optional_decimal(item[name], name)
                if item["evidence_mode"] not in {
                    "none",
                    "optional_comment",
                    "required_comment",
                }:
                    raise AssessmentTemplateImportError("evidence mode is unsupported")
                if item["criticality"] not in {"normal", "critical", "stop_factor"}:
                    raise AssessmentTemplateImportError("criticality is invalid")
                if not isinstance(item["config"], dict):
                    raise AssessmentTemplateImportError("item config is invalid")
                options = item["options"]
                if not isinstance(options, list) or len(options) > MAX_OPTIONS:
                    raise AssessmentTemplateImportError("options are invalid")
                if item["response_type"] == "single_choice" and len(options) < 2:
                    raise AssessmentTemplateImportError("choice item requires options")
                if item["response_type"] != "single_choice" and options:
                    raise AssessmentTemplateImportError("non-choice item has options")
                option_codes: set[str] = set()
                for option in options:
                    option = _object(option, "option")
                    _exact_keys(
                        option,
                        {"code", "label", "numeric_value", "disqualifying"},
                        "option",
                    )
                    option_code = _slug(option["code"], "option code")
                    if option_code in option_codes:
                        raise AssessmentTemplateImportError("duplicate option code")
                    option_codes.add(option_code)
                    _bounded_text(option["label"], "option label", 255)
                    _optional_decimal(option["numeric_value"], "numeric value")
                    if type(option["disqualifying"]) is not bool:
                        raise AssessmentTemplateImportError(
                            "option disqualifying flag is invalid"
                        )
                metrics = item["metrics"]
                if not isinstance(metrics, list) or not metrics:
                    raise AssessmentTemplateImportError("item requires metric mapping")
                metric_codes: set[str] = set()
                for mapping in metrics:
                    mapping = _object(mapping, "metric mapping")
                    _exact_keys(
                        mapping,
                        {"code", "weight", "direction"},
                        "metric mapping",
                    )
                    if mapping["code"] not in _METRICS:
                        raise AssessmentTemplateImportError("unknown metric code")
                    if mapping["code"] in metric_codes:
                        raise AssessmentTemplateImportError("duplicate metric mapping")
                    metric_codes.add(mapping["code"])
                    _optional_positive_decimal(mapping["weight"], "metric weight")
                    if mapping["direction"] not in {"positive", "inverse"}:
                        raise AssessmentTemplateImportError(
                            "metric direction is invalid"
                        )


class AssessmentTemplateImportService:
    """Caller-owned transaction; one company lock serializes imports."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def plan(self, company_id: UUID, manifest: ReviewedManifest) -> ImportPlan:
        template = manifest.document["template"]
        source = manifest.document["source"]
        existing = (
            await self._session.execute(
                select(AssessmentTemplate).where(
                    AssessmentTemplate.company_id == company_id,
                    AssessmentTemplate.scope == "company",
                    AssessmentTemplate.code == template["code"],
                    AssessmentTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        next_version = 1
        action = "create"
        if existing is not None:
            provenance = (
                await self._session.execute(
                    select(AssessmentTemplateImportSource.id)
                    .join(
                        AssessmentTemplateVersion,
                        AssessmentTemplateVersion.id
                        == AssessmentTemplateImportSource.template_version_id,
                    )
                    .where(
                        AssessmentTemplateVersion.template_id == existing.id,
                        AssessmentTemplateImportSource.source_sha256
                        == bytes.fromhex(source["sha256"]),
                        AssessmentTemplateImportSource.manifest_sha256
                        == bytes.fromhex(manifest.manifest_sha256),
                    )
                )
            ).scalar_one_or_none()
            if provenance is not None:
                action = "no_op"
                next_version = None
            else:
                draft = (
                    await self._session.execute(
                        select(AssessmentTemplateVersion.id).where(
                            AssessmentTemplateVersion.template_id == existing.id,
                            AssessmentTemplateVersion.status == "draft",
                        )
                    )
                ).scalar_one_or_none()
                if draft is not None:
                    action = "conflict"
                    next_version = None
                else:
                    action = "new_version"
                    maximum_version = (
                        await self._session.execute(
                            select(func.max(AssessmentTemplateVersion.version)).where(
                                AssessmentTemplateVersion.template_id == existing.id
                            )
                        )
                    ).scalar_one()
                    next_version = (maximum_version or 0) + 1
        return ImportPlan(
            action=action,
            template_code=template["code"],
            next_version=next_version,
            section_count=len(template["sections"]),
            item_count=sum(len(value["items"]) for value in template["sections"]),
            source_filename=source["filename"],
            source_sha256=source["sha256"],
            manifest_sha256=manifest.manifest_sha256,
        )

    async def apply(
        self,
        company_id: UUID,
        manifest: ReviewedManifest,
        now: datetime,
    ) -> ImportResult:
        company = (
            await self._session.execute(
                select(Company).where(Company.id == company_id).with_for_update()
            )
        ).scalar_one_or_none()
        if company is None or company.deleted_at is not None:
            raise AssessmentTemplateImportError("company is unavailable")
        plan = await self.plan(company_id, manifest)
        if plan.action == "conflict":
            raise AssessmentTemplateImportConflict("company template has a draft")
        template_data = manifest.document["template"]
        existing = (
            await self._session.execute(
                select(AssessmentTemplate).where(
                    AssessmentTemplate.company_id == company_id,
                    AssessmentTemplate.scope == "company",
                    AssessmentTemplate.code == template_data["code"],
                    AssessmentTemplate.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if plan.action == "no_op":
            version = (
                await self._session.execute(
                    select(AssessmentTemplateVersion)
                    .join(
                        AssessmentTemplateImportSource,
                        AssessmentTemplateImportSource.template_version_id
                        == AssessmentTemplateVersion.id,
                    )
                    .where(
                        AssessmentTemplateVersion.template_id == existing.id,
                        AssessmentTemplateImportSource.source_sha256
                        == bytes.fromhex(plan.source_sha256),
                        AssessmentTemplateImportSource.manifest_sha256
                        == bytes.fromhex(plan.manifest_sha256),
                    )
                )
            ).scalar_one()
            return ImportResult(
                "no_op",
                existing.id,
                version.id,
                version.version,
                plan.section_count,
                plan.item_count,
                0,
            )

        methodology_data = template_data["methodology"]
        methodology_version = (
            await self._session.execute(
                select(func.max(AssessmentMethodology.version)).where(
                    AssessmentMethodology.company_id == company_id,
                    AssessmentMethodology.owner_type == "company",
                    AssessmentMethodology.code == methodology_data["code"],
                    AssessmentMethodology.deleted_at.is_(None),
                )
            )
        ).scalar_one() or 0
        methodology = AssessmentMethodology(
            owner_type="company",
            company_id=company_id,
            code=methodology_data["code"],
            title=methodology_data["title"],
            body=methodology_data["body"],
            version=methodology_version + 1,
            status="draft",
            published_at=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(methodology)
        if existing is None:
            existing = AssessmentTemplate(
                scope="company",
                company_id=company_id,
                source_library_version_id=None,
                code=template_data["code"],
                name=template_data["name"],
                activity_type=template_data["activity_type"],
                status="active",
                created_at=now,
                updated_at=now,
            )
            self._session.add(existing)
        else:
            if (
                existing.name != template_data["name"]
                or existing.activity_type != template_data["activity_type"]
            ):
                raise AssessmentTemplateImportConflict(
                    "existing template identity differs from manifest"
                )
        await self._session.flush()
        version = AssessmentTemplateVersion(
            template_id=existing.id,
            version=plan.next_version,
            edit_revision=1,
            status="draft",
            methodology_id=methodology.id,
            local_description=template_data["description"],
            change_note=(
                "Initial reviewed Excel import"
                if plan.action == "create"
                else "Reviewed Excel source changed"
            ),
            published_at=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(version)
        await self._session.flush()

        metric_definitions = await self._metric_definitions()
        mapping_count = 0
        for section_order, section_data in enumerate(template_data["sections"]):
            section = AssessmentTemplateSection(
                template_version_id=version.id,
                parent_section_id=None,
                code=section_data["code"],
                title=section_data["title"],
                description=section_data["description"],
                section_kind=section_data["kind"],
                sort_order=section_order,
                weight=_decimal_or_none(section_data["weight"]),
                created_at=now,
                updated_at=now,
            )
            self._session.add(section)
            await self._session.flush()
            for item_order, item_data in enumerate(section_data["items"]):
                item = AssessmentTemplateItem(
                    template_version_id=version.id,
                    section_id=section.id,
                    code=item_data["code"],
                    prompt=item_data["prompt"],
                    guidance=item_data["guidance"],
                    response_type=item_data["response_type"],
                    is_required=item_data["required"],
                    sort_order=item_order,
                    weight=_decimal_or_none(item_data["weight"]),
                    min_value=_decimal_or_none(item_data["min_value"]),
                    max_value=_decimal_or_none(item_data["max_value"]),
                    passing_value=_decimal_or_none(item_data["passing_value"]),
                    evidence_mode=item_data["evidence_mode"],
                    criticality=item_data["criticality"],
                    config=item_data["config"],
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(item)
                await self._session.flush()
                self._session.add_all(
                    [
                        AssessmentTemplateItemOption(
                            item_id=item.id,
                            code=option["code"],
                            label=option["label"],
                            sort_order=option_order,
                            numeric_value=_decimal_or_none(option["numeric_value"]),
                            is_disqualifying=option["disqualifying"],
                            created_at=now,
                            updated_at=now,
                        )
                        for option_order, option in enumerate(item_data["options"])
                    ]
                )
                for mapping in item_data["metrics"]:
                    self._session.add(
                        AssessmentItemMetricMapping(
                            template_version_id=version.id,
                            item_id=item.id,
                            metric_definition_id=metric_definitions[mapping["code"]].id,
                            contribution_weight=_decimal_or_none(mapping["weight"]),
                            direction=mapping["direction"],
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    mapping_count += 1

        scoring = template_data["scoring"]
        self._session.add(
            AssessmentScoringPolicy(
                template_version_id=version.id,
                algorithm=scoring["algorithm"],
                version=scoring["version"],
                config=scoring["config"],
                created_at=now,
                updated_at=now,
            )
        )
        source = manifest.document["source"]
        self._session.add(
            AssessmentTemplateImportSource(
                template_version_id=version.id,
                source_filename=source["filename"],
                provenance=source["provenance"],
                source_sha256=bytes.fromhex(source["sha256"]),
                manifest_sha256=bytes.fromhex(manifest.manifest_sha256),
                imported_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await self._session.flush()
        return ImportResult(
            plan.action,
            existing.id,
            version.id,
            version.version,
            plan.section_count,
            plan.item_count,
            mapping_count,
        )

    async def _metric_definitions(self) -> dict[str, AssessmentMetricDefinition]:
        rows = (
            (
                await self._session.execute(
                    select(AssessmentMetricDefinition).where(
                        AssessmentMetricDefinition.code.in_(_METRICS),
                        AssessmentMetricDefinition.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        result = {value.code: value for value in rows}
        if set(result) != set(_METRICS):
            raise AssessmentTemplateImportError("metric taxonomy is unavailable")
        return result


class AssessmentLibraryImportService:
    """Idempotently materialize publication-ready reviewed methods in the library."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def _lock_template_code(self, template_code: str) -> None:
        """Serialize first publication without inventing a mutable library parent."""
        bind = self._session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_key = int.from_bytes(
            sha256(f"assessment-library:{template_code}".encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    async def plan(self, manifest: ReviewedManifest) -> ImportPlan:
        template = manifest.document["template"]
        source = manifest.document["source"]
        existing = await self._session.scalar(
            select(AssessmentTemplate).where(
                AssessmentTemplate.scope == "library",
                AssessmentTemplate.company_id.is_(None),
                AssessmentTemplate.code == template["code"],
                AssessmentTemplate.deleted_at.is_(None),
            )
        )
        action = "blocked_missing_weights"
        next_version: int | None = None
        if manifest.publication_ready():
            action = "create" if existing is None else "no_op"
            next_version = 1 if existing is None else None
        return ImportPlan(
            action=action,
            template_code=template["code"],
            next_version=next_version,
            section_count=len(template["sections"]),
            item_count=sum(len(value["items"]) for value in template["sections"]),
            source_filename=source["filename"],
            source_sha256=source["sha256"],
            manifest_sha256=manifest.manifest_sha256,
        )

    async def apply(
        self, manifest: ReviewedManifest, now: datetime
    ) -> ImportResult:
        await self._lock_template_code(manifest.document["template"]["code"])
        plan = await self.plan(manifest)
        if plan.action == "blocked_missing_weights":
            raise AssessmentTemplateImportConflict(
                "incomplete reviewed methodology cannot enter the library"
            )
        template_data = manifest.document["template"]
        existing = await self._session.scalar(
            select(AssessmentTemplate).where(
                AssessmentTemplate.scope == "library",
                AssessmentTemplate.company_id.is_(None),
                AssessmentTemplate.code == template_data["code"],
                AssessmentTemplate.deleted_at.is_(None),
            )
        )
        if existing is not None:
            version = await self._session.scalar(
                select(AssessmentTemplateVersion)
                .where(
                    AssessmentTemplateVersion.template_id == existing.id,
                    AssessmentTemplateVersion.status == "published",
                )
                .order_by(AssessmentTemplateVersion.version.desc())
                .limit(1)
            )
            if version is None:
                raise AssessmentTemplateImportConflict(
                    "library template exists without a published version"
                )
            return ImportResult(
                "no_op",
                existing.id,
                version.id,
                version.version,
                plan.section_count,
                plan.item_count,
                0,
            )

        methodology_data = template_data["methodology"]
        methodology = AssessmentMethodology(
            owner_type="system",
            company_id=None,
            code=methodology_data["code"],
            title=methodology_data["title"],
            body=methodology_data["body"],
            version=methodology_data["version"],
            status="published",
            published_at=now,
            created_at=now,
            updated_at=now,
        )
        template = AssessmentTemplate(
            scope="library",
            company_id=None,
            source_library_version_id=None,
            code=template_data["code"],
            name=template_data["name"],
            activity_type=template_data["activity_type"],
            status="active",
            created_at=now,
            updated_at=now,
        )
        self._session.add_all([methodology, template])
        await self._session.flush()
        version = AssessmentTemplateVersion(
            template_id=template.id,
            version=1,
            edit_revision=1,
            status="published",
            methodology_id=methodology.id,
            local_description=template_data["description"],
            change_note="Reviewed Excel methodology library import",
            published_at=now,
            created_at=now,
            updated_at=now,
        )
        self._session.add(version)
        await self._session.flush()
        metric_definitions = await AssessmentTemplateImportService(
            self._session
        )._metric_definitions()
        mapping_count = 0
        for section_order, section_data in enumerate(template_data["sections"]):
            section = AssessmentTemplateSection(
                template_version_id=version.id,
                parent_section_id=None,
                code=section_data["code"],
                title=section_data["title"],
                description=section_data["description"],
                section_kind=section_data["kind"],
                sort_order=section_order,
                weight=_decimal_or_none(section_data["weight"]),
                created_at=now,
                updated_at=now,
            )
            self._session.add(section)
            await self._session.flush()
            for item_order, item_data in enumerate(section_data["items"]):
                item = AssessmentTemplateItem(
                    template_version_id=version.id,
                    section_id=section.id,
                    code=item_data["code"],
                    prompt=item_data["prompt"],
                    guidance=item_data["guidance"],
                    response_type=item_data["response_type"],
                    is_required=item_data["required"],
                    sort_order=item_order,
                    weight=_decimal_or_none(item_data["weight"]),
                    min_value=_decimal_or_none(item_data["min_value"]),
                    max_value=_decimal_or_none(item_data["max_value"]),
                    passing_value=_decimal_or_none(item_data["passing_value"]),
                    evidence_mode=item_data["evidence_mode"],
                    criticality=item_data["criticality"],
                    config=item_data["config"],
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(item)
                await self._session.flush()
                self._session.add_all(
                    AssessmentTemplateItemOption(
                        item_id=item.id,
                        code=option["code"],
                        label=option["label"],
                        sort_order=option_order,
                        numeric_value=_decimal_or_none(option["numeric_value"]),
                        is_disqualifying=option["disqualifying"],
                        created_at=now,
                        updated_at=now,
                    )
                    for option_order, option in enumerate(item_data["options"])
                )
                for mapping in item_data["metrics"]:
                    self._session.add(
                        AssessmentItemMetricMapping(
                            template_version_id=version.id,
                            item_id=item.id,
                            metric_definition_id=metric_definitions[mapping["code"]].id,
                            contribution_weight=_decimal_or_none(mapping["weight"]),
                            direction=mapping["direction"],
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    mapping_count += 1
        scoring = template_data["scoring"]
        self._session.add_all(
            [
                AssessmentScoringPolicy(
                    template_version_id=version.id,
                    algorithm=scoring["algorithm"],
                    version=scoring["version"],
                    config=scoring["config"],
                    created_at=now,
                    updated_at=now,
                ),
                AssessmentTemplateImportSource(
                    template_version_id=version.id,
                    source_filename=plan.source_filename,
                    provenance="read_only_methodology_source",
                    source_sha256=bytes.fromhex(plan.source_sha256),
                    manifest_sha256=bytes.fromhex(plan.manifest_sha256),
                    imported_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        await self._session.flush()
        return ImportResult(
            "create",
            template.id,
            version.id,
            1,
            plan.section_count,
            plan.item_count,
            mapping_count,
        )


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AssessmentTemplateImportError(f"{label} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise AssessmentTemplateImportError(f"{label} fields are invalid")


def _slug(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise AssessmentTemplateImportError(f"{label} is invalid")
    return value


def _bounded_text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise AssessmentTemplateImportError(f"{label} is invalid")
    return value


def _bounded_optional_text(value: Any, label: str, limit: int) -> None:
    if value is not None and (
        not isinstance(value, str) or not value.strip() or len(value) > limit
    ):
        raise AssessmentTemplateImportError(f"{label} is invalid")


def _positive_decimal(value: Any, label: str) -> Decimal:
    numeric = _required_decimal(value, label)
    if numeric <= 0:
        raise AssessmentTemplateImportError(f"{label} must be positive")
    return numeric


def _optional_positive_decimal(value: Any, label: str) -> Decimal | None:
    if value is None:
        return None
    return _positive_decimal(value, label)


def _optional_decimal(value: Any, label: str) -> Decimal | None:
    if value is None:
        return None
    return _required_decimal(value, label)


def _required_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise AssessmentTemplateImportError(f"{label} is invalid")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise AssessmentTemplateImportError(f"{label} is invalid") from error
    if not numeric.is_finite():
        raise AssessmentTemplateImportError(f"{label} is invalid")
    return numeric


def _decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
