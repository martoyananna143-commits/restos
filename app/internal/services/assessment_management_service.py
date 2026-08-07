"""Account-scoped assessment assignment management service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentAttemptAnswer,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateVersion,
    EmployeeAssignment,
    EmployeeProfile,
    Position,
)
from app.internal.services.access_decision_service import AccessDecisionService


READ_PERMISSION = "assessment.assignment.read"
MANAGE_PERMISSION = "assessment.assignment.manage"
ACTIVE_ASSIGNMENT_INDEX = "uq_assessment_assignments_active_employee_version"


class AssessmentManagementPermissionDenied(Exception):
    pass


class AssessmentManagementNotFound(Exception):
    pass


class AssessmentManagementDuplicate(Exception):
    pass


class AssessmentManagementAlreadyCompleted(Exception):
    pass


class AssessmentManagementStateConflict(Exception):
    pass


class AssessmentManagementInvalid(Exception):
    pass


@dataclass(frozen=True)
class CreateAssignment:
    account_id: UUID
    company_id: UUID
    employee_profile_id: UUID
    template_version_id: UUID
    due_at: datetime | None
    now: datetime


class AssessmentManagementService:
    """Management domain service; callers own transaction boundaries."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_employees(
        self,
        account_id: UUID,
        company_id: UUID,
        now: datetime,
        *,
        q: str | None,
        limit: int,
        after: UUID | None,
    ) -> list[dict[str, Any]]:
        await self._require_read(account_id, company_id, now)
        if after is not None and not await self._employee_cursor_exists(
            company_id, after, now
        ):
            raise AssessmentManagementNotFound("employee cursor not found")
        statement = (
            select(EmployeeProfile, Position)
            .join(
                EmployeeAssignment,
                (EmployeeAssignment.employee_profile_id == EmployeeProfile.id)
                & (EmployeeAssignment.company_id == EmployeeProfile.company_id),
            )
            .join(
                Position,
                (Position.id == EmployeeAssignment.position_id)
                & (Position.company_id == EmployeeAssignment.company_id),
            )
            .where(*self._active_employee_predicate(company_id, now))
            .order_by(
                EmployeeProfile.id,
                EmployeeAssignment.is_primary.desc(),
                EmployeeAssignment.id,
            )
            .distinct(EmployeeProfile.id)
            .limit(limit)
        )
        if q:
            statement = statement.where(
                EmployeeProfile.full_name.ilike(f"%{q.strip()}%")
            )
        if after is not None:
            statement = statement.where(EmployeeProfile.id > after)
        rows = (await self._session.execute(statement)).all()
        return [
            {
                "employee_profile_id": profile.id,
                "display_name": profile.full_name,
                "position_title": position.name,
                "status": "active",
            }
            for profile, position in rows
        ]

    async def list_templates(
        self, account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, Any]]:
        await self._require_read(account_id, company_id, now)
        rows = (
            await self._session.execute(
                select(AssessmentTemplate, AssessmentTemplateVersion)
                .join(
                    AssessmentTemplateVersion,
                    AssessmentTemplateVersion.template_id
                    == AssessmentTemplate.id,
                )
                .where(
                    AssessmentTemplate.company_id == company_id,
                    AssessmentTemplate.scope == "company",
                    AssessmentTemplate.status == "active",
                    AssessmentTemplate.deleted_at.is_(None),
                    AssessmentTemplateVersion.status == "published",
                )
                .order_by(
                    AssessmentTemplate.name,
                    AssessmentTemplateVersion.version,
                    AssessmentTemplateVersion.id,
                )
            )
        ).all()
        return [
            {
                "template_id": template.id,
                "template_version_id": version.id,
                "name": template.name,
                "activity_type": template.activity_type,
                "version": version.version,
                "published_at": version.published_at,
            }
            for template, version in rows
        ]

    async def list_assignments(
        self,
        account_id: UUID,
        company_id: UUID,
        now: datetime,
        *,
        status: str | None,
        limit: int,
        after: UUID | None,
    ) -> list[dict[str, Any]]:
        await self._require_read(account_id, company_id, now)
        if after is not None and not await self._assignment_cursor_exists(
            company_id, after
        ):
            raise AssessmentManagementNotFound("assignment cursor not found")
        statement = self._assignment_projection().where(
            AssessmentAssignment.company_id == company_id
        )
        if status is not None:
            statement = statement.where(AssessmentAssignment.status == status)
        if after is not None:
            statement = statement.where(AssessmentAssignment.id > after)
        rows = (
            await self._session.execute(
                statement.order_by(AssessmentAssignment.id).limit(limit)
            )
        ).all()
        return [self._project_assignment(row) for row in rows]

    async def assignment_detail(
        self,
        account_id: UUID,
        company_id: UUID,
        assignment_id: UUID,
        now: datetime,
    ) -> dict[str, Any]:
        await self._require_read(account_id, company_id, now)
        row = (
            await self._session.execute(
                self._assignment_projection().where(
                    AssessmentAssignment.id == assignment_id,
                    AssessmentAssignment.company_id == company_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise AssessmentManagementNotFound("assessment assignment not found")
        return self._project_assignment(row)

    async def create_assignment(self, command: CreateAssignment) -> dict[str, Any]:
        now = self._aware(command.now, "now")
        due_at = (
            self._aware(command.due_at, "due_at")
            if command.due_at is not None
            else None
        )
        if due_at is not None and due_at <= now:
            raise AssessmentManagementInvalid("due_at must be in the future")
        await self._require_manage(command.account_id, command.company_id, now)
        employee = await self._lock_employee(
            command.company_id, command.employee_profile_id, now
        )
        await self._lock_template(command.company_id, command.template_version_id)
        assigner_profile_id = (
            await self._session.execute(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.company_id == command.company_id,
                    EmployeeProfile.account_id == command.account_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        assignment = AssessmentAssignment(
            company_id=command.company_id,
            employee_profile_id=employee.id,
            template_version_id=command.template_version_id,
            assigned_by_employee_profile_id=assigner_profile_id,
            assigned_by_account_id=command.account_id,
            status="assigned",
            assigned_at=now,
            due_at=due_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(assignment)
                await self._session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) == ACTIVE_ASSIGNMENT_INDEX:
                raise AssessmentManagementDuplicate(
                    "duplicate active assignment"
                ) from error
            raise
        return await self.assignment_detail(
            command.account_id, command.company_id, assignment.id, now
        )

    async def revoke_assignment(
        self,
        account_id: UUID,
        company_id: UUID,
        assignment_id: UUID,
        now: datetime,
    ) -> dict[str, Any]:
        checked_now = self._aware(now, "now")
        await self._require_manage(account_id, company_id, checked_now)
        attempt_id = (
            await self._session.execute(
                select(AssessmentAttempt.id).where(
                    AssessmentAttempt.assignment_id == assignment_id
                )
            )
        ).scalar_one_or_none()
        if attempt_id is not None:
            await self._session.execute(
                select(AssessmentAttempt.id)
                .where(AssessmentAttempt.id == attempt_id)
                .with_for_update()
            )
        assignment = (
            await self._session.execute(
                select(AssessmentAssignment)
                .where(
                    AssessmentAssignment.id == assignment_id,
                    AssessmentAssignment.company_id == company_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if assignment is None:
            raise AssessmentManagementNotFound("assessment assignment not found")
        if attempt_id is None:
            await self._session.execute(
                select(AssessmentAttempt.id)
                .where(AssessmentAttempt.assignment_id == assignment_id)
                .with_for_update()
            )
        if assignment.status == "completed":
            raise AssessmentManagementAlreadyCompleted(
                "assessment already completed"
            )
        if assignment.status == "revoked":
            return await self.assignment_detail(
                account_id, company_id, assignment_id, checked_now
            )
        if assignment.status not in {"assigned", "in_progress"}:
            raise AssessmentManagementStateConflict("assessment state conflict")
        assignment.status = "revoked"
        assignment.revoked_at = checked_now
        await self._session.flush()
        return await self.assignment_detail(
            account_id, company_id, assignment_id, checked_now
        )

    async def _require_read(
        self, account_id: UUID, company_id: UUID, now: datetime
    ) -> None:
        access = AccessDecisionService(self._session)
        if not (
            await access.can_in_company(
                account_id, company_id, READ_PERMISSION, now
            )
            or await access.can_in_company(
                account_id, company_id, MANAGE_PERMISSION, now
            )
        ):
            raise AssessmentManagementPermissionDenied("permission denied")

    async def _require_manage(
        self, account_id: UUID, company_id: UUID, now: datetime
    ) -> None:
        if not await AccessDecisionService(self._session).can_in_company(
            account_id, company_id, MANAGE_PERMISSION, now
        ):
            raise AssessmentManagementPermissionDenied("permission denied")

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AssessmentManagementInvalid(
                f"{name} must be timezone-aware"
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            direct = getattr(current, "constraint_name", None)
            if isinstance(direct, str):
                return direct
            diagnostic = getattr(current, "diag", None)
            name = getattr(diagnostic, "constraint_name", None)
            if isinstance(name, str):
                return name
            current = getattr(current, "orig", None) or getattr(
                current, "__cause__", None
            )
        return None

    @staticmethod
    def _active_employee_predicate(
        company_id: UUID, now: datetime
    ) -> tuple[Any, ...]:
        return (
            EmployeeProfile.company_id == company_id,
            EmployeeProfile.employment_status == "active",
            EmployeeProfile.deleted_at.is_(None),
            EmployeeAssignment.company_id == company_id,
            EmployeeAssignment.status == "active",
            EmployeeAssignment.deleted_at.is_(None),
            EmployeeAssignment.starts_at <= now,
            or_(EmployeeAssignment.ends_at.is_(None), EmployeeAssignment.ends_at > now),
            Position.company_id == company_id,
            Position.is_active.is_(True),
            Position.deleted_at.is_(None),
        )

    async def _employee_cursor_exists(
        self, company_id: UUID, employee_id: UUID, now: datetime
    ) -> bool:
        statement = (
            select(EmployeeProfile.id)
            .join(
                EmployeeAssignment,
                EmployeeAssignment.employee_profile_id == EmployeeProfile.id,
            )
            .join(Position, Position.id == EmployeeAssignment.position_id)
            .where(
                EmployeeProfile.id == employee_id,
                *self._active_employee_predicate(company_id, now),
            )
        )
        return (
            await self._session.execute(statement)
        ).scalar_one_or_none() is not None

    async def _assignment_cursor_exists(
        self, company_id: UUID, assignment_id: UUID
    ) -> bool:
        return (
            await self._session.execute(
                select(AssessmentAssignment.id).where(
                    AssessmentAssignment.id == assignment_id,
                    AssessmentAssignment.company_id == company_id,
                )
            )
        ).scalar_one_or_none() is not None

    async def _lock_employee(
        self, company_id: UUID, employee_id: UUID, now: datetime
    ) -> EmployeeProfile:
        row = (
            await self._session.execute(
                select(EmployeeProfile)
                .join(
                    EmployeeAssignment,
                    EmployeeAssignment.employee_profile_id == EmployeeProfile.id,
                )
                .join(Position, Position.id == EmployeeAssignment.position_id)
                .where(
                    EmployeeProfile.id == employee_id,
                    *self._active_employee_predicate(company_id, now),
                )
                .with_for_update(of=EmployeeProfile)
            )
        ).scalars().first()
        if row is None:
            raise AssessmentManagementNotFound(
                "assessment management resource not found"
            )
        return row

    async def _lock_template(self, company_id: UUID, version_id: UUID) -> None:
        row = (
            await self._session.execute(
                select(AssessmentTemplateVersion.id)
                .join(
                    AssessmentTemplate,
                    AssessmentTemplateVersion.template_id
                    == AssessmentTemplate.id,
                )
                .where(
                    AssessmentTemplateVersion.id == version_id,
                    AssessmentTemplateVersion.status == "published",
                    AssessmentTemplate.company_id == company_id,
                    AssessmentTemplate.scope == "company",
                    AssessmentTemplate.status == "active",
                    AssessmentTemplate.deleted_at.is_(None),
                )
                .with_for_update(of=AssessmentTemplateVersion)
            )
        ).scalar_one_or_none()
        if row is None:
            raise AssessmentManagementNotFound(
                "assessment management resource not found"
            )

    @staticmethod
    def _assignment_projection():
        answered = (
            select(func.count(AssessmentAttemptAnswer.id))
            .where(AssessmentAttemptAnswer.attempt_id == AssessmentAttempt.id)
            .correlate(AssessmentAttempt)
            .scalar_subquery()
        )
        required = (
            select(func.count(AssessmentTemplateItem.id))
            .where(
                AssessmentTemplateItem.template_version_id
                == AssessmentAssignment.template_version_id,
                AssessmentTemplateItem.is_required.is_(True),
            )
            .correlate(AssessmentAssignment)
            .scalar_subquery()
        )
        total = (
            select(func.count(AssessmentTemplateItem.id))
            .where(
                AssessmentTemplateItem.template_version_id
                == AssessmentAssignment.template_version_id
            )
            .correlate(AssessmentAssignment)
            .scalar_subquery()
        )
        return (
            select(
                AssessmentAssignment,
                EmployeeProfile.full_name,
                Position.name.label("position_title"),
                AssessmentTemplate.id.label("template_id"),
                AssessmentTemplate.name.label("template_name"),
                AssessmentTemplateVersion.version.label("template_version"),
                AssessmentAttempt.started_at,
                AssessmentAttempt.last_saved_at,
                AssessmentAttempt.submitted_at,
                AssessmentAttempt.result_json,
                answered.label("answered_count"),
                required.label("required_count"),
                total.label("total_count"),
            )
            .join(
                EmployeeProfile,
                EmployeeProfile.id == AssessmentAssignment.employee_profile_id,
            )
            .outerjoin(
                EmployeeAssignment,
                (EmployeeAssignment.employee_profile_id == EmployeeProfile.id)
                & (EmployeeAssignment.company_id == EmployeeProfile.company_id)
                & (EmployeeAssignment.is_primary.is_(True)),
            )
            .outerjoin(Position, Position.id == EmployeeAssignment.position_id)
            .join(
                AssessmentTemplateVersion,
                AssessmentTemplateVersion.id
                == AssessmentAssignment.template_version_id,
            )
            .join(
                AssessmentTemplate,
                AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
            )
            .outerjoin(
                AssessmentAttempt,
                AssessmentAttempt.assignment_id == AssessmentAssignment.id,
            )
        )

    @staticmethod
    def _project_assignment(row: Any) -> dict[str, Any]:
        assignment = row[0]
        completion = None
        if (
            assignment.status == "completed"
            and isinstance(row.result_json, dict)
            and row.result_json.get("scoring_algorithm") == "completion_v1"
        ):
            completion = {
                "scoring_algorithm": "completion_v1",
                "submitted_at": row.submitted_at,
                "answered_count": row.answered_count,
                "required_count": row.required_count,
                "total_count": row.total_count,
            }
        return {
            "id": assignment.id,
            "status": assignment.status,
            "assigned_at": assignment.assigned_at,
            "due_at": assignment.due_at,
            "revoked_at": assignment.revoked_at,
            "completed_at": assignment.completed_at,
            "employee": {
                "employee_profile_id": assignment.employee_profile_id,
                "display_name": row.full_name,
                "position_title": row.position_title,
            },
            "template": {
                "template_id": row.template_id,
                "template_version_id": assignment.template_version_id,
                "name": row.template_name,
                "version": row.template_version,
            },
            "progress": {
                "answered_count": row.answered_count,
                "required_count": row.required_count,
                "total_count": row.total_count,
                "started_at": row.started_at,
                "last_saved_at": row.last_saved_at,
                "submitted_at": row.submitted_at,
                "completion": completion,
            },
        }
