"""Company/venue operational walkthrough orchestration over assessment attempts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentScoringPolicy,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
    EmployeeAssignment,
    EmployeeProfile,
    Venue,
)
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.assessment_attempt_service import AssessmentAttemptService


MANAGE_PERMISSION = "assessment.assignment.manage"
ACTIVE_ASSIGNMENT_INDEX = "uq_assessment_assignments_active_employee_version"


class OperationalWalkthroughPermissionDenied(Exception):
    pass


class OperationalWalkthroughNotFound(Exception):
    pass


class OperationalWalkthroughConflict(Exception):
    pass


class AssessmentOperationalWalkthroughService:
    """Start venue-owned runs; employee profile identifies only the executor."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_templates(
        self, account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, Any]]:
        checked_now = self._aware(now)
        await self._require_manage(account_id, company_id, checked_now)
        section_count = (
            select(func.count(AssessmentTemplateSection.id))
            .where(
                AssessmentTemplateSection.template_version_id
                == AssessmentTemplateVersion.id
            )
            .correlate(AssessmentTemplateVersion)
            .scalar_subquery()
        )
        item_count = (
            select(func.count(AssessmentTemplateItem.id))
            .where(
                AssessmentTemplateItem.template_version_id
                == AssessmentTemplateVersion.id
            )
            .correlate(AssessmentTemplateVersion)
            .scalar_subquery()
        )
        rows = (
            await self._session.execute(
                select(
                    AssessmentTemplate,
                    AssessmentTemplateVersion,
                    AssessmentScoringPolicy,
                    section_count,
                    item_count,
                )
                .join(
                    AssessmentTemplateVersion,
                    AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
                )
                .join(
                    AssessmentScoringPolicy,
                    AssessmentScoringPolicy.template_version_id
                    == AssessmentTemplateVersion.id,
                )
                .where(
                    AssessmentTemplate.company_id == company_id,
                    AssessmentTemplate.scope == "company",
                    AssessmentTemplate.status == "active",
                    AssessmentTemplate.deleted_at.is_(None),
                    AssessmentTemplate.activity_type == "walkthrough",
                    AssessmentTemplateVersion.status == "published",
                    AssessmentScoringPolicy.algorithm == "weighted_v1",
                )
                .order_by(AssessmentTemplate.name, AssessmentTemplateVersion.version)
            )
        ).all()
        return [
            {
                "template_id": template.id,
                "template_version_id": version.id,
                "name": template.name,
                "version": version.version,
                "section_count": int(sections),
                "item_count": int(items),
                "scoring_algorithm": policy.algorithm,
                "scoring_ready": True,
            }
            for template, version, policy, sections, items in rows
        ]

    async def start(
        self,
        account_id: UUID,
        company_id: UUID,
        venue_id: UUID,
        template_version_id: UUID,
        now: datetime,
    ) -> dict[str, Any]:
        checked_now = self._aware(now)
        await self._require_manage(account_id, company_id, checked_now)
        executor_id = await self._executor(account_id, company_id, checked_now)
        venue = await self._session.scalar(
            select(Venue.id).where(
                Venue.id == venue_id,
                Venue.company_id == company_id,
                Venue.status == "active",
                Venue.deleted_at.is_(None),
            )
        )
        if venue is None:
            raise OperationalWalkthroughNotFound("venue is unavailable")
        version = await self._session.scalar(
            select(AssessmentTemplateVersion)
            .join(
                AssessmentTemplate,
                AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
            )
            .join(
                AssessmentScoringPolicy,
                AssessmentScoringPolicy.template_version_id
                == AssessmentTemplateVersion.id,
            )
            .where(
                AssessmentTemplateVersion.id == template_version_id,
                AssessmentTemplateVersion.status == "published",
                AssessmentTemplate.company_id == company_id,
                AssessmentTemplate.scope == "company",
                AssessmentTemplate.status == "active",
                AssessmentTemplate.deleted_at.is_(None),
                AssessmentTemplate.activity_type == "walkthrough",
                AssessmentScoringPolicy.algorithm == "weighted_v1",
            )
            .with_for_update(of=AssessmentTemplateVersion)
        )
        if version is None:
            raise OperationalWalkthroughNotFound("walkthrough is unavailable")
        existing = await self._session.scalar(
            select(AssessmentAssignment).where(
                AssessmentAssignment.company_id == company_id,
                AssessmentAssignment.employee_profile_id == executor_id,
                AssessmentAssignment.template_version_id == version.id,
                AssessmentAssignment.purpose == "operational_walkthrough",
                AssessmentAssignment.status.in_(("assigned", "in_progress")),
            )
        )
        if existing is not None:
            if existing.venue_id != venue_id:
                raise OperationalWalkthroughConflict(
                    "another walkthrough is already active"
                )
            return await AssessmentAttemptService(self._session).create_or_resume(
                account_id, existing.id, checked_now
            )
        assignment = AssessmentAssignment(
            company_id=company_id,
            venue_id=venue_id,
            employee_profile_id=executor_id,
            template_version_id=version.id,
            assigned_by_employee_profile_id=executor_id,
            assigned_by_account_id=account_id,
            status="assigned",
            purpose="operational_walkthrough",
            assigned_at=checked_now,
            due_at=None,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(assignment)
                await self._session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) != ACTIVE_ASSIGNMENT_INDEX:
                raise
            existing = await self._session.scalar(
                select(AssessmentAssignment).where(
                    AssessmentAssignment.company_id == company_id,
                    AssessmentAssignment.employee_profile_id == executor_id,
                    AssessmentAssignment.template_version_id == version.id,
                    AssessmentAssignment.purpose == "operational_walkthrough",
                    AssessmentAssignment.status.in_(("assigned", "in_progress")),
                )
            )
            if existing is None or existing.venue_id != venue_id:
                raise OperationalWalkthroughConflict(
                    "another walkthrough is already active"
                ) from error
            assignment = existing
        return await AssessmentAttemptService(self._session).create_or_resume(
            account_id, assignment.id, checked_now
        )

    async def _executor(
        self, account_id: UUID, company_id: UUID, now: datetime
    ) -> UUID:
        value = await self._session.scalar(
            select(EmployeeProfile.id)
            .join(
                EmployeeAssignment,
                EmployeeAssignment.employee_profile_id == EmployeeProfile.id,
            )
            .where(
                EmployeeProfile.account_id == account_id,
                EmployeeProfile.company_id == company_id,
                EmployeeProfile.employment_status == "active",
                EmployeeProfile.deleted_at.is_(None),
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.status == "active",
                EmployeeAssignment.starts_at <= now,
                (
                    EmployeeAssignment.ends_at.is_(None)
                    | (EmployeeAssignment.ends_at > now)
                ),
                EmployeeAssignment.deleted_at.is_(None),
            )
            .limit(1)
        )
        if value is None:
            raise OperationalWalkthroughPermissionDenied(
                "active executor profile is unavailable"
            )
        return value

    async def _require_manage(
        self, account_id: UUID, company_id: UUID, now: datetime
    ) -> None:
        if not await AccessDecisionService(self._session).can_in_company(
            account_id, company_id, MANAGE_PERMISSION, now
        ):
            raise OperationalWalkthroughPermissionDenied("permission denied")

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        current: object | None = error
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
            current = (
                getattr(current, "orig", None)
                or getattr(current, "__cause__", None)
                or getattr(current, "__context__", None)
            )
        return None

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise OperationalWalkthroughConflict("now must be timezone-aware")
        return value.astimezone(timezone.utc)
