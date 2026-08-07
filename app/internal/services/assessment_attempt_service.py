"""Atomic employee assessment attempt lifecycle service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
import math
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentAttemptAnswer,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
    EmployeeAssignment,
    EmployeeProfile,
)


MAX_ANSWERS = 5_000
MAX_TEXT_LENGTH = 10_000
MAX_MULTI_OPTIONS = 100
MAX_DOCUMENT_BYTES = 1_000_000


class AssessmentAttemptNotFound(Exception):
    pass


class AssessmentAttemptReadOnly(Exception):
    pass


class AssessmentAttemptInvalid(Exception):
    pass


class AssessmentAttemptIncomplete(Exception):
    pass


class AssessmentAttemptRevisionConflict(Exception):
    def __init__(self, current_revision: int, answers: list[dict[str, Any]]):
        super().__init__("assessment attempt revision conflict")
        self.current_revision = current_revision
        self.answers = answers


@dataclass(frozen=True)
class AnswerInput:
    item_id: UUID
    answer_type: str
    value: Any


@dataclass(frozen=True)
class ReplaceDraft:
    account_id: UUID
    attempt_id: UUID
    expected_revision: int
    answers: list[AnswerInput]
    now: datetime


class AssessmentAttemptService:
    """Domain service; callers own commit and rollback boundaries."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_assignments(self, account_id: UUID, now: datetime) -> list[dict[str, Any]]:
        rows = (await self._session.execute(
            select(AssessmentAssignment, AssessmentTemplate, AssessmentTemplateVersion)
            .join(EmployeeProfile, EmployeeProfile.id == AssessmentAssignment.employee_profile_id)
            .join(AssessmentTemplateVersion, AssessmentTemplateVersion.id == AssessmentAssignment.template_version_id)
            .join(AssessmentTemplate, AssessmentTemplate.id == AssessmentTemplateVersion.template_id)
            .where(EmployeeProfile.account_id == account_id, EmployeeProfile.deleted_at.is_(None))
            .order_by(AssessmentAssignment.assigned_at.desc(), AssessmentAssignment.id)
        )).all()
        result = []
        for assignment, template, version in rows:
            if await self._authorized(assignment, account_id, now):
                result.append(self._assignment_summary(assignment, template, version, now))
        return result

    async def assignment_detail(self, account_id: UUID, assignment_id: UUID, now: datetime) -> dict[str, Any]:
        assignment = await self._assignment_for_account(account_id, assignment_id, now)
        return await self._assignment_document(assignment, now)

    async def create_or_resume(self, account_id: UUID, assignment_id: UUID, now: datetime) -> dict[str, Any]:
        assignment = await self._locked_assignment_for_account(account_id, assignment_id, now)
        self._ensure_mutable_assignment(assignment, now)
        await self._validate_assignment_template(assignment)
        existing = (await self._session.execute(
            select(AssessmentAttempt).where(AssessmentAttempt.assignment_id == assignment.id)
        )).scalar_one_or_none()
        if existing is None:
            existing = AssessmentAttempt(
                assignment_id=assignment.id,
                account_id=account_id,
                employee_profile_id=assignment.employee_profile_id,
                template_version_id=assignment.template_version_id,
                status="draft",
                revision=0,
                started_at=now,
            )
            self._session.add(existing)
            if assignment.status == "assigned":
                assignment.status = "in_progress"
            await self._session.flush()
        return await self._attempt_document(existing, assignment, now)

    async def read_attempt(self, account_id: UUID, attempt_id: UUID, now: datetime) -> dict[str, Any]:
        attempt, assignment = await self._attempt_for_account(account_id, attempt_id, now)
        return await self._attempt_document(attempt, assignment, now)

    async def replace_draft(self, command: ReplaceDraft) -> dict[str, Any]:
        attempt, assignment = await self._locked_attempt_for_account(command.account_id, command.attempt_id, command.now)
        self._ensure_draft_mutable(attempt, assignment, command.now)
        if attempt.revision != command.expected_revision:
            raise AssessmentAttemptRevisionConflict(attempt.revision, await self._answers(attempt.id))
        normalized = await self._validate_answers(attempt.template_version_id, command.answers)
        await self._session.execute(delete(AssessmentAttemptAnswer).where(AssessmentAttemptAnswer.attempt_id == attempt.id))
        self._session.add_all([
            AssessmentAttemptAnswer(
                attempt_id=attempt.id,
                item_id=value["item_id"],
                answer_type=value["answer_type"],
                value_json=value["value"],
            )
            for value in normalized
        ])
        attempt.revision += 1
        attempt.last_saved_at = command.now
        await self._session.flush()
        return await self._attempt_document(attempt, assignment, command.now)

    async def submit(self, account_id: UUID, attempt_id: UUID, now: datetime) -> dict[str, Any]:
        attempt, assignment = await self._locked_attempt_for_account(account_id, attempt_id, now, lock_assignment=True)
        if attempt.status == "submitted":
            return dict(attempt.result_json or {})
        self._ensure_draft_mutable(attempt, assignment, now)
        answers = await self._answers(attempt.id)
        await self._validate_answers(
            attempt.template_version_id,
            [AnswerInput(row["item_id"], row["answer_type"], row["value"]) for row in answers],
        )
        items = (await self._session.execute(
            select(AssessmentTemplateItem).where(AssessmentTemplateItem.template_version_id == attempt.template_version_id)
        )).scalars().all()
        answered = {row["item_id"] for row in answers}
        required = {item.id for item in items if item.is_required}
        if not required.issubset(answered):
            raise AssessmentAttemptIncomplete("required answers are missing")
        result = {
            "scoring_algorithm": "completion_v1",
            "submitted_at": now.isoformat(),
            "answered_count": len(answered),
            "required_count": len(required),
            "total_count": len(items),
        }
        attempt.status = "submitted"
        attempt.submitted_at = now
        attempt.result_json = result
        assignment.status = "completed"
        assignment.completed_at = now
        await self._session.flush()
        return result

    async def result(self, account_id: UUID, attempt_id: UUID, now: datetime) -> dict[str, Any]:
        attempt, _ = await self._attempt_for_account(account_id, attempt_id, now)
        if attempt.status != "submitted" or not attempt.result_json:
            raise AssessmentAttemptNotFound("result not found")
        return dict(attempt.result_json)

    async def _authorized(self, assignment: AssessmentAssignment, account_id: UUID, now: datetime) -> bool:
        profile = (await self._session.execute(select(EmployeeProfile).where(
            EmployeeProfile.id == assignment.employee_profile_id,
            EmployeeProfile.account_id == account_id,
            EmployeeProfile.company_id == assignment.company_id,
            EmployeeProfile.employment_status == "active",
            EmployeeProfile.deleted_at.is_(None),
        ))).scalar_one_or_none()
        if profile is None:
            return False
        membership = (await self._session.execute(select(EmployeeAssignment.id).where(
            EmployeeAssignment.employee_profile_id == profile.id,
            EmployeeAssignment.company_id == assignment.company_id,
            EmployeeAssignment.status == "active",
            EmployeeAssignment.starts_at <= now,
            (EmployeeAssignment.ends_at.is_(None) | (EmployeeAssignment.ends_at > now)),
            EmployeeAssignment.deleted_at.is_(None),
        ).limit(1))).scalar_one_or_none()
        return membership is not None

    async def _assignment_for_account(self, account_id: UUID, assignment_id: UUID, now: datetime) -> AssessmentAssignment:
        assignment = await self._session.get(AssessmentAssignment, assignment_id)
        if assignment is None or not await self._authorized(assignment, account_id, now):
            raise AssessmentAttemptNotFound("assessment not found")
        return assignment

    async def _locked_assignment_for_account(self, account_id: UUID, assignment_id: UUID, now: datetime) -> AssessmentAssignment:
        assignment = (await self._session.execute(select(AssessmentAssignment).where(AssessmentAssignment.id == assignment_id).with_for_update())).scalar_one_or_none()
        if assignment is None or not await self._authorized(assignment, account_id, now):
            raise AssessmentAttemptNotFound("assessment not found")
        return assignment

    async def _attempt_for_account(self, account_id: UUID, attempt_id: UUID, now: datetime) -> tuple[AssessmentAttempt, AssessmentAssignment]:
        row = (await self._session.execute(select(AssessmentAttempt, AssessmentAssignment).join(AssessmentAssignment).where(
            AssessmentAttempt.id == attempt_id, AssessmentAttempt.account_id == account_id
        ))).one_or_none()
        if row is None or not await self._authorized(row[1], account_id, now):
            raise AssessmentAttemptNotFound("assessment not found")
        return row[0], row[1]

    async def _locked_attempt_for_account(self, account_id: UUID, attempt_id: UUID, now: datetime, *, lock_assignment: bool = False) -> tuple[AssessmentAttempt, AssessmentAssignment]:
        attempt = (await self._session.execute(select(AssessmentAttempt).where(
            AssessmentAttempt.id == attempt_id, AssessmentAttempt.account_id == account_id
        ).with_for_update())).scalar_one_or_none()
        if attempt is None:
            raise AssessmentAttemptNotFound("assessment not found")
        query = select(AssessmentAssignment).where(AssessmentAssignment.id == attempt.assignment_id)
        if lock_assignment:
            query = query.with_for_update()
        assignment = (await self._session.execute(query)).scalar_one()
        if not await self._authorized(assignment, account_id, now):
            raise AssessmentAttemptNotFound("assessment not found")
        return attempt, assignment

    def _ensure_mutable_assignment(self, assignment: AssessmentAssignment, now: datetime) -> None:
        if assignment.status in {"revoked", "completed"} or (assignment.due_at and assignment.due_at <= now):
            raise AssessmentAttemptReadOnly("assessment is read only")

    def _ensure_draft_mutable(self, attempt: AssessmentAttempt, assignment: AssessmentAssignment, now: datetime) -> None:
        if attempt.status != "draft":
            raise AssessmentAttemptReadOnly("assessment is read only")
        self._ensure_mutable_assignment(assignment, now)

    async def _validate_assignment_template(self, assignment: AssessmentAssignment) -> None:
        row = (await self._session.execute(select(AssessmentTemplateVersion, AssessmentTemplate).join(
            AssessmentTemplate,
            AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
        ).where(
            AssessmentTemplateVersion.id == assignment.template_version_id,
            AssessmentTemplateVersion.status == "published",
            AssessmentTemplate.status == "active",
            AssessmentTemplate.deleted_at.is_(None),
            AssessmentTemplate.scope == "company",
            AssessmentTemplate.company_id == assignment.company_id,
        ))).one_or_none()
        if row is None:
            raise AssessmentAttemptNotFound("assessment not found")

    async def _validate_answers(self, template_version_id: UUID, answers: list[AnswerInput]) -> list[dict[str, Any]]:
        if len(answers) > MAX_ANSWERS:
            raise AssessmentAttemptInvalid("too many answers")
        if len({answer.item_id for answer in answers}) != len(answers):
            raise AssessmentAttemptInvalid("duplicate item")
        items = {item.id: item for item in (await self._session.execute(select(AssessmentTemplateItem).where(
            AssessmentTemplateItem.template_version_id == template_version_id
        ))).scalars().all()}
        option_rows = (await self._session.execute(select(AssessmentTemplateItemOption).where(
            AssessmentTemplateItemOption.item_id.in_(items.keys())
        ))).scalars().all() if items else []
        options: dict[UUID, set[UUID]] = {}
        for option in option_rows:
            options.setdefault(option.item_id, set()).add(option.id)
        normalized = []
        for answer in answers:
            item = items.get(answer.item_id)
            if item is None or answer.answer_type != item.response_type:
                raise AssessmentAttemptInvalid("invalid assessment answer")
            value = self._normalize_value(answer.answer_type, answer.value, options.get(answer.item_id, set()))
            if value is not None:
                normalized.append({"item_id": answer.item_id, "answer_type": answer.answer_type, "value": value})
        try:
            encoded = json.dumps(normalized, default=str, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError) as error:
            raise AssessmentAttemptInvalid("invalid assessment answer") from error
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise AssessmentAttemptInvalid("assessment document too large")
        return normalized

    def _normalize_value(self, answer_type: str, value: Any, allowed_options: set[UUID]) -> Any:
        if value is None or value == "" or value == []:
            return None
        if answer_type == "boolean":
            if type(value) is not bool:
                raise AssessmentAttemptInvalid("invalid boolean")
            return value
        if answer_type == "integer":
            if type(value) is not int:
                raise AssessmentAttemptInvalid("invalid integer")
            return value
        if answer_type in {"decimal", "score"}:
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                raise AssessmentAttemptInvalid("invalid numeric")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise AssessmentAttemptInvalid("invalid numeric")
            return str(value)
        if answer_type == "text":
            if not isinstance(value, str):
                raise AssessmentAttemptInvalid("invalid text")
            value = value.strip()
            if not value:
                return None
            if len(value) > MAX_TEXT_LENGTH:
                raise AssessmentAttemptInvalid("text too long")
            return value
        if answer_type in {"date", "time"}:
            if not isinstance(value, str):
                raise AssessmentAttemptInvalid("invalid temporal value")
            try:
                parsed = date.fromisoformat(value) if answer_type == "date" else time.fromisoformat(value)
            except ValueError as error:
                raise AssessmentAttemptInvalid("invalid temporal value") from error
            if parsed.isoformat() != value:
                raise AssessmentAttemptInvalid("non-canonical temporal value")
            return value
        if answer_type == "single_choice":
            try:
                selected = UUID(str(value))
            except (ValueError, TypeError) as error:
                raise AssessmentAttemptInvalid("invalid option") from error
            if selected not in allowed_options:
                raise AssessmentAttemptInvalid("invalid option")
            return str(selected)
        if answer_type == "multi_choice":
            if not isinstance(value, list) or len(value) > MAX_MULTI_OPTIONS:
                raise AssessmentAttemptInvalid("invalid options")
            try:
                selected = [UUID(str(option)) for option in value]
            except (ValueError, TypeError) as error:
                raise AssessmentAttemptInvalid("invalid options") from error
            if len(set(selected)) != len(selected) or not set(selected).issubset(allowed_options):
                raise AssessmentAttemptInvalid("invalid options")
            return [str(option) for option in selected]
        raise AssessmentAttemptInvalid("unsupported answer type")

    async def _answers(self, attempt_id: UUID) -> list[dict[str, Any]]:
        rows = (await self._session.execute(select(AssessmentAttemptAnswer).where(
            AssessmentAttemptAnswer.attempt_id == attempt_id
        ).order_by(AssessmentAttemptAnswer.item_id))).scalars().all()
        return [{"item_id": row.item_id, "answer_type": row.answer_type, "value": row.value_json} for row in rows]

    async def _template_document(self, version_id: UUID) -> dict[str, Any]:
        sections = (await self._session.execute(select(AssessmentTemplateSection).where(
            AssessmentTemplateSection.template_version_id == version_id
        ).order_by(AssessmentTemplateSection.sort_order, AssessmentTemplateSection.id))).scalars().all()
        items = (await self._session.execute(select(AssessmentTemplateItem).where(
            AssessmentTemplateItem.template_version_id == version_id
        ).order_by(AssessmentTemplateItem.sort_order, AssessmentTemplateItem.id))).scalars().all()
        options = (await self._session.execute(select(AssessmentTemplateItemOption).where(
            AssessmentTemplateItemOption.item_id.in_([item.id for item in items])
        ).order_by(AssessmentTemplateItemOption.sort_order, AssessmentTemplateItemOption.id))).scalars().all() if items else []
        by_item: dict[UUID, list[dict[str, Any]]] = {}
        for option in options:
            by_item.setdefault(option.item_id, []).append({"id": option.id, "label": option.label, "sort_order": option.sort_order})
        by_section: dict[UUID, list[dict[str, Any]]] = {}
        for item in items:
            safe_config = {key: value for key, value in item.config.items() if key in {"placeholder", "max_length"}}
            by_section.setdefault(item.section_id, []).append({
                "id": item.id, "prompt": item.prompt, "guidance": item.guidance,
                "answer_type": item.response_type, "required": item.is_required,
                "sort_order": item.sort_order, "config": safe_config,
                "options": by_item.get(item.id, []),
            })
        return {"version_id": version_id, "sections": [{
            "id": section.id, "parent_section_id": section.parent_section_id,
            "title": section.title, "description": section.description,
            "sort_order": section.sort_order, "items": by_section.get(section.id, []),
        } for section in sections]}

    async def _assignment_document(self, assignment: AssessmentAssignment, now: datetime) -> dict[str, Any]:
        await self._validate_assignment_template(assignment)
        version, template = (await self._session.execute(select(AssessmentTemplateVersion, AssessmentTemplate).join(
            AssessmentTemplate,
            AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
        ).where(
            AssessmentTemplateVersion.id == assignment.template_version_id
        ))).one()
        result = self._assignment_summary(assignment, template, version, now)
        result["document"] = await self._template_document(version.id)
        return result

    def _assignment_summary(self, assignment: AssessmentAssignment, template: AssessmentTemplate, version: AssessmentTemplateVersion, now: datetime) -> dict[str, Any]:
        return {
            "id": assignment.id, "company_id": assignment.company_id,
            "status": assignment.status, "assigned_at": assignment.assigned_at,
            "due_at": assignment.due_at, "template_name": template.name,
            "template_version": version.version,
            "read_only": assignment.status in {"revoked", "completed"} or bool(assignment.due_at and assignment.due_at <= now),
        }

    async def _attempt_document(self, attempt: AssessmentAttempt, assignment: AssessmentAssignment, now: datetime) -> dict[str, Any]:
        reason = None
        if attempt.status == "submitted": reason = "submitted"
        elif assignment.status == "revoked": reason = "revoked"
        elif assignment.due_at and assignment.due_at <= now: reason = "expired"
        return {
            "id": attempt.id, "assignment_id": assignment.id, "status": attempt.status,
            "revision": attempt.revision, "started_at": attempt.started_at,
            "last_saved_at": attempt.last_saved_at, "submitted_at": attempt.submitted_at,
            "read_only": reason is not None, "read_only_reason": reason,
            "document": await self._template_document(attempt.template_version_id),
            "answers": await self._answers(attempt.id),
        }
