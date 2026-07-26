"""Read-only assessment template catalog queries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.assessment_template import (
    AssessmentMethodology,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
)


class AssessmentCatalogNotFound(Exception):
    """Requested catalog resource is unavailable in its public context."""


@dataclass(frozen=True)
class ListLibraryTemplates:
    activity_type: str | None = None
    query: str | None = None
    limit: int = 50
    offset: int = 0


class AssessmentCatalogService:
    """Execute SELECT-only catalog operations without transaction ownership."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_library_templates(
        self, request: ListLibraryTemplates
    ) -> list[dict]:
        latest = (
            select(
                AssessmentTemplateVersion.template_id,
                func.max(AssessmentTemplateVersion.version).label("version"),
            )
            .where(AssessmentTemplateVersion.status == "published")
            .group_by(AssessmentTemplateVersion.template_id)
            .subquery()
        )
        statement = (
            select(
                AssessmentTemplate,
                AssessmentTemplateVersion,
                AssessmentMethodology,
            )
            .join(latest, latest.c.template_id == AssessmentTemplate.id)
            .join(
                AssessmentTemplateVersion,
                (AssessmentTemplateVersion.template_id == latest.c.template_id)
                & (AssessmentTemplateVersion.version == latest.c.version),
            )
            .join(
                AssessmentMethodology,
                AssessmentMethodology.id
                == AssessmentTemplateVersion.methodology_id,
            )
            .where(
                AssessmentTemplate.scope == "library",
                AssessmentTemplate.status == "active",
                AssessmentTemplate.deleted_at.is_(None),
                AssessmentMethodology.status == "published",
                AssessmentMethodology.deleted_at.is_(None),
            )
        )
        if request.activity_type is not None:
            statement = statement.where(
                AssessmentTemplate.activity_type == request.activity_type
            )
        if request.query:
            escaped = (
                request.query.strip().replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            statement = statement.where(
                or_(
                    AssessmentTemplate.name.ilike(pattern, escape="\\"),
                    AssessmentTemplate.code.ilike(pattern, escape="\\"),
                )
            )
        rows = (
            await self._session.execute(
                statement.order_by(
                    AssessmentTemplate.name,
                    AssessmentTemplate.code,
                    AssessmentTemplate.id,
                )
                .limit(request.limit)
                .offset(request.offset)
            )
        ).all()
        counts = await self._counts([version.id for _, version, _ in rows])
        return [
            self._summary(template, version, methodology, counts[version.id])
            for template, version, methodology in rows
        ]

    async def get_library_template(
        self, template_id: UUID, version_id: UUID | None = None
    ) -> dict:
        template = await self._available_template(template_id, scope="library")
        statement = select(AssessmentTemplateVersion).where(
            AssessmentTemplateVersion.template_id == template.id,
            AssessmentTemplateVersion.status == "published",
        )
        if version_id is not None:
            statement = statement.where(
                AssessmentTemplateVersion.id == version_id
            )
        else:
            statement = statement.order_by(
                AssessmentTemplateVersion.version.desc()
            ).limit(1)
        version = (await self._session.execute(statement)).scalar_one_or_none()
        if version is None:
            raise AssessmentCatalogNotFound("assessment is unavailable")
        methodology = await self._published_methodology(version.methodology_id)
        return await self._document(template, version, methodology)

    async def list_company_templates(self, company_id: UUID) -> list[dict]:
        templates = (
            await self._session.execute(
                select(AssessmentTemplate)
                .where(
                    AssessmentTemplate.scope == "company",
                    AssessmentTemplate.company_id == company_id,
                    AssessmentTemplate.status == "active",
                    AssessmentTemplate.deleted_at.is_(None),
                )
                .order_by(
                    AssessmentTemplate.name,
                    AssessmentTemplate.code,
                    AssessmentTemplate.id,
                )
            )
        ).scalars().all()
        result: list[dict] = []
        for template in templates:
            versions = (
                await self._session.execute(
                    select(AssessmentTemplateVersion)
                    .where(AssessmentTemplateVersion.template_id == template.id)
                    .order_by(AssessmentTemplateVersion.version.desc())
                )
            ).scalars().all()
            draft = next((row for row in versions if row.status == "draft"), None)
            published = next(
                (row for row in versions if row.status == "published"), None
            )
            methodology_id = (
                draft.methodology_id
                if draft is not None
                else published.methodology_id if published is not None else None
            )
            methodology = (
                await self._published_methodology(methodology_id)
                if methodology_id is not None
                else None
            )
            counts = await self._counts(
                [row.id for row in (draft, published) if row is not None]
            )
            result.append(
                {
                    "template_id": template.id,
                    "code": template.code,
                    "name": template.name,
                    "activity_type": template.activity_type,
                    "status": template.status,
                    "source_library_version_id": template.source_library_version_id,
                    "methodology": self._methodology_summary(methodology),
                    "latest_draft": (
                        self._version_summary(draft, counts[draft.id])
                        if draft is not None
                        else None
                    ),
                    "latest_published": (
                        self._version_summary(published, counts[published.id])
                        if published is not None
                        else None
                    ),
                }
            )
        return result

    async def get_company_template_version(
        self, company_id: UUID, template_id: UUID, version_id: UUID
    ) -> dict:
        template = await self._available_template(
            template_id, scope="company", company_id=company_id
        )
        version = (
            await self._session.execute(
                select(AssessmentTemplateVersion).where(
                    AssessmentTemplateVersion.id == version_id,
                    AssessmentTemplateVersion.template_id == template.id,
                )
            )
        ).scalar_one_or_none()
        if version is None:
            raise AssessmentCatalogNotFound("assessment is unavailable")
        methodology = (
            await self._session.execute(
                select(AssessmentMethodology).where(
                    AssessmentMethodology.id == version.methodology_id,
                    AssessmentMethodology.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if methodology is None:
            raise AssessmentCatalogNotFound("assessment is unavailable")
        return await self._document(template, version, methodology)

    async def _available_template(
        self,
        template_id: UUID,
        *,
        scope: str,
        company_id: UUID | None = None,
    ) -> AssessmentTemplate:
        statement = select(AssessmentTemplate).where(
            AssessmentTemplate.id == template_id,
            AssessmentTemplate.scope == scope,
            AssessmentTemplate.status == "active",
            AssessmentTemplate.deleted_at.is_(None),
        )
        if company_id is not None:
            statement = statement.where(
                AssessmentTemplate.company_id == company_id
            )
        template = (await self._session.execute(statement)).scalar_one_or_none()
        if template is None:
            raise AssessmentCatalogNotFound("assessment is unavailable")
        return template

    async def _published_methodology(
        self, methodology_id: UUID
    ) -> AssessmentMethodology:
        methodology = (
            await self._session.execute(
                select(AssessmentMethodology).where(
                    AssessmentMethodology.id == methodology_id,
                    AssessmentMethodology.status == "published",
                    AssessmentMethodology.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if methodology is None:
            raise AssessmentCatalogNotFound("assessment is unavailable")
        return methodology

    async def _counts(
        self, version_ids: list[UUID]
    ) -> dict[UUID, tuple[int, int, int]]:
        result = {version_id: (0, 0, 0) for version_id in version_ids}
        if not version_ids:
            return result
        section_rows = (
            await self._session.execute(
                select(
                    AssessmentTemplateSection.template_version_id,
                    func.count(),
                )
                .where(
                    AssessmentTemplateSection.template_version_id.in_(
                        version_ids
                    )
                )
                .group_by(AssessmentTemplateSection.template_version_id)
            )
        ).all()
        item_rows = (
            await self._session.execute(
                select(
                    AssessmentTemplateItem.template_version_id,
                    func.count(),
                )
                .where(
                    AssessmentTemplateItem.template_version_id.in_(version_ids)
                )
                .group_by(AssessmentTemplateItem.template_version_id)
            )
        ).all()
        option_rows = (
            await self._session.execute(
                select(
                    AssessmentTemplateItem.template_version_id,
                    func.count(AssessmentTemplateItemOption.id),
                )
                .join(
                    AssessmentTemplateItemOption,
                    AssessmentTemplateItemOption.item_id
                    == AssessmentTemplateItem.id,
                )
                .where(
                    AssessmentTemplateItem.template_version_id.in_(version_ids)
                )
                .group_by(AssessmentTemplateItem.template_version_id)
            )
        ).all()
        sections = dict(section_rows)
        items = dict(item_rows)
        options = dict(option_rows)
        return {
            version_id: (
                sections.get(version_id, 0),
                items.get(version_id, 0),
                options.get(version_id, 0),
            )
            for version_id in version_ids
        }

    async def _document(
        self,
        template: AssessmentTemplate,
        version: AssessmentTemplateVersion,
        methodology: AssessmentMethodology,
    ) -> dict:
        sections = (
            await self._session.execute(
                select(AssessmentTemplateSection)
                .where(
                    AssessmentTemplateSection.template_version_id == version.id
                )
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
        option_map: dict[UUID, list[dict]] = {}
        for option in options:
            option_map.setdefault(option.item_id, []).append(
                self._row(option, {"item_id"})
            )
        item_map: dict[UUID, list[dict]] = {}
        for item in items:
            value = self._row(
                item, {"template_version_id", "section_id"}
            )
            value["config"] = deepcopy(item.config)
            value["options"] = option_map.get(item.id, [])
            item_map.setdefault(item.section_id, []).append(value)
        section_codes = {section.id: section.code for section in sections}
        tree: list[dict] = []
        for section in sections:
            value = self._row(
                section, {"template_version_id", "parent_section_id"}
            )
            value["parent_code"] = section_codes.get(
                section.parent_section_id
            )
            value["items"] = item_map.get(section.id, [])
            tree.append(value)
        return {
            "template": {
                "id": template.id,
                "scope": template.scope,
                "company_id": template.company_id,
                "source_library_version_id": template.source_library_version_id,
                "code": template.code,
                "name": template.name,
                "activity_type": template.activity_type,
                "status": template.status,
            },
            "version": self._version_summary(
                version, (len(sections), len(items), len(options))
            ),
            "methodology": {
                "id": methodology.id,
                "code": methodology.code,
                "title": methodology.title,
                "body": methodology.body,
                "version": methodology.version,
                "owner_type": methodology.owner_type,
                "status": methodology.status,
            },
            "sections": tree,
        }

    @staticmethod
    def _summary(template, version, methodology, counts) -> dict:
        return {
            "template_id": template.id,
            "version_id": version.id,
            "code": template.code,
            "name": template.name,
            "activity_type": template.activity_type,
            "version": version.version,
            "methodology": {
                "title": methodology.title,
                "version": methodology.version,
            },
            "local_description": version.local_description,
            "section_count": counts[0],
            "item_count": counts[1],
            "option_count": counts[2],
            "published_at": version.published_at,
        }

    @staticmethod
    def _version_summary(version, counts) -> dict:
        return {
            "version_id": version.id,
            "version": version.version,
            "status": version.status,
            "edit_revision": version.edit_revision,
            "local_description": version.local_description,
            "change_note": version.change_note,
            "published_at": version.published_at,
            "section_count": counts[0],
            "item_count": counts[1],
            "option_count": counts[2],
        }

    @staticmethod
    def _methodology_summary(methodology) -> dict | None:
        if methodology is None:
            return None
        return {
            "id": methodology.id,
            "title": methodology.title,
            "version": methodology.version,
        }

    @staticmethod
    def _row(value, excluded: set[str]) -> dict:
        return {
            column.name: getattr(value, column.name)
            for column in value.__table__.columns
            if column.name not in excluded
        }
