"""Atomic employee assessment attempt lifecycle service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import math
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentAttemptAnswer,
    AssessmentItemMetricMapping,
    AssessmentMetricDefinition,
    AssessmentMetricObservation,
    AssessmentScoringPolicy,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
    Company,
    EmployeeAssignment,
    EmployeeProfile,
)
from app.internal.services.assessment_weighted_scoring_service import (
    MetricMapping,
    WeightedItem,
    WeightedScoringInvalid,
    calculate_metric_results,
    calculate_weighted_result,
)
from app.internal.services.access_decision_service import AccessDecisionService


MAX_ANSWERS = 5_000
MAX_TEXT_LENGTH = 10_000
MAX_MULTI_OPTIONS = 100
MAX_DOCUMENT_BYTES = 1_000_000
MAX_ATTEMPT_SECTIONS = 1_000


class AssessmentAttemptNotFound(Exception):
    pass


class AssessmentAttemptReadOnly(Exception):
    pass


class AssessmentAttemptInvalid(Exception):
    pass


class AssessmentAssignmentPeriodInvalid(Exception):
    pass


class AssessmentAttemptIncomplete(Exception):
    pass


class AssessmentAttemptRevisionConflict(Exception):
    def __init__(
        self,
        current_revision: int,
        answers: list[dict[str, Any]],
        ui_metadata: dict[str, Any],
    ):
        super().__init__("assessment attempt revision conflict")
        self.current_revision = current_revision
        self.answers = answers
        self.ui_metadata = ui_metadata


@dataclass(frozen=True)
class AnswerInput:
    item_id: UUID
    answer_type: str
    value: Any
    comment: str | None = None


@dataclass(frozen=True)
class ReplaceDraft:
    account_id: UUID
    attempt_id: UUID
    expected_revision: int
    answers: list[AnswerInput]
    now: datetime
    section_order: list[UUID] | None = None


class AssessmentAttemptService:
    """Domain service; callers own commit and rollback boundaries."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_assignments(
        self,
        account_id: UUID,
        now: datetime,
        *,
        company_id: UUID | None = None,
        history_period: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        checked_now = self._aware_datetime(now, "now")
        history_bounds: tuple[datetime, datetime] | None = None
        if company_id is not None:
            timezone_name = await self._company_timezone(company_id)
            history_bounds = self._history_bounds(
                checked_now,
                timezone_name,
                history_period,
                date_from,
                date_to,
            )
        elif history_period is not None or date_from is not None or date_to is not None:
            raise AssessmentAssignmentPeriodInvalid(
                "company_id is required for a history period"
            )
        rows = (
            await self._session.execute(
                select(
                    AssessmentAssignment,
                    AssessmentTemplate,
                    AssessmentTemplateVersion,
                    AssessmentAttempt,
                )
                .join(
                    EmployeeProfile,
                    EmployeeProfile.id == AssessmentAssignment.employee_profile_id,
                )
                .join(
                    AssessmentTemplateVersion,
                    AssessmentTemplateVersion.id
                    == AssessmentAssignment.template_version_id,
                )
                .join(
                    AssessmentTemplate,
                    AssessmentTemplate.id == AssessmentTemplateVersion.template_id,
                )
                .outerjoin(
                    AssessmentAttempt,
                    AssessmentAttempt.assignment_id == AssessmentAssignment.id,
                )
                .where(
                    EmployeeProfile.account_id == account_id,
                    EmployeeProfile.deleted_at.is_(None),
                    *(
                        (AssessmentAssignment.company_id == company_id,)
                        if company_id is not None
                        else ()
                    ),
                )
                .order_by(
                    AssessmentAssignment.assigned_at.desc(), AssessmentAssignment.id
                )
            )
        ).all()
        result = []
        for assignment, template, version, attempt in rows:
            if not await self._authorized(assignment, account_id, checked_now):
                continue
            if assignment.status == "completed" and history_bounds is not None:
                start, end = history_bounds
                if (
                    attempt is None
                    or attempt.submitted_at is None
                    or not start <= attempt.submitted_at.astimezone(timezone.utc) < end
                ):
                    continue
            result.append(
                self._assignment_summary(
                    assignment,
                    template,
                    version,
                    checked_now,
                    submitted_at=(attempt.submitted_at if attempt else None),
                )
            )
        return result

    async def _company_timezone(self, company_id: UUID) -> str:
        value = (
            await self._session.execute(
                select(Company.timezone).where(
                    Company.id == company_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if value is None:
            raise AssessmentAssignmentPeriodInvalid("company is unavailable")
        return value

    @classmethod
    def _history_bounds(
        cls,
        now: datetime,
        timezone_name: str,
        history_period: str | None,
        date_from: date | None,
        date_to: date | None,
    ) -> tuple[datetime, datetime]:
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise AssessmentAssignmentPeriodInvalid(
                "company timezone is invalid"
            ) from error
        today = now.astimezone(local_timezone).date()
        period = history_period or "today"
        if period == "today":
            start_date = end_date = today
        elif period == "yesterday":
            start_date = end_date = today - timedelta(days=1)
        elif period == "previous_week":
            current_week = today - timedelta(days=today.weekday())
            start_date = current_week - timedelta(days=7)
            end_date = current_week - timedelta(days=1)
        elif period == "previous_month":
            current_month = today.replace(day=1)
            end_date = current_month - timedelta(days=1)
            start_date = end_date.replace(day=1)
        elif period == "custom":
            if date_from is None or date_to is None:
                raise AssessmentAssignmentPeriodInvalid(
                    "custom period requires date_from and date_to"
                )
            start_date, end_date = date_from, date_to
        else:
            raise AssessmentAssignmentPeriodInvalid("unknown history period")
        if start_date > end_date or end_date - start_date > timedelta(days=366):
            raise AssessmentAssignmentPeriodInvalid("history period is invalid")
        start = datetime.combine(start_date, time.min, local_timezone)
        end = datetime.combine(end_date + timedelta(days=1), time.min, local_timezone)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

    @staticmethod
    def _aware_datetime(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AssessmentAssignmentPeriodInvalid(f"{name} must be timezone-aware")
        return value.astimezone(timezone.utc)

    async def assignment_detail(
        self, account_id: UUID, assignment_id: UUID, now: datetime
    ) -> dict[str, Any]:
        assignment = await self._assignment_for_account(account_id, assignment_id, now)
        return await self._assignment_document(assignment, now)

    async def create_or_resume(
        self, account_id: UUID, assignment_id: UUID, now: datetime
    ) -> dict[str, Any]:
        assignment = await self._locked_assignment_for_account(
            account_id, assignment_id, now
        )
        self._ensure_mutable_assignment(assignment, now)
        await self._validate_assignment_template(assignment)
        existing = (
            await self._session.execute(
                select(AssessmentAttempt).where(
                    AssessmentAttempt.assignment_id == assignment.id
                )
            )
        ).scalar_one_or_none()
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

    async def read_attempt(
        self, account_id: UUID, attempt_id: UUID, now: datetime
    ) -> dict[str, Any]:
        attempt, assignment = await self._attempt_for_account(
            account_id, attempt_id, now
        )
        return await self._attempt_document(attempt, assignment, now)

    async def replace_draft(self, command: ReplaceDraft) -> dict[str, Any]:
        attempt, assignment = await self._locked_attempt_for_account(
            command.account_id, command.attempt_id, command.now
        )
        self._ensure_draft_mutable(attempt, assignment, command.now)
        if attempt.revision != command.expected_revision:
            raise AssessmentAttemptRevisionConflict(
                attempt.revision,
                await self._answers(attempt.id),
                self._attempt_ui_metadata(attempt),
            )
        normalized = await self._validate_answers(
            attempt.template_version_id, command.answers
        )
        if command.section_order is not None:
            attempt.ui_metadata_json = await self._validate_ui_metadata(
                attempt.template_version_id, command.section_order
            )
        await self._session.execute(
            delete(AssessmentAttemptAnswer).where(
                AssessmentAttemptAnswer.attempt_id == attempt.id
            )
        )
        self._session.add_all(
            [
                AssessmentAttemptAnswer(
                    attempt_id=attempt.id,
                    item_id=value["item_id"],
                    answer_type=value["answer_type"],
                    value_json=value["value"],
                    comment=value["comment"],
                )
                for value in normalized
            ]
        )
        attempt.revision += 1
        attempt.last_saved_at = command.now
        await self._session.flush()
        return await self._attempt_document(attempt, assignment, command.now)

    async def _validate_ui_metadata(
        self, template_version_id: UUID, section_order: list[UUID]
    ) -> dict[str, Any]:
        if len(section_order) > MAX_ATTEMPT_SECTIONS or len(set(section_order)) != len(
            section_order
        ):
            raise AssessmentAttemptInvalid("invalid section order")
        expected = set(
            (
                await self._session.execute(
                    select(AssessmentTemplateSection.id).where(
                        AssessmentTemplateSection.template_version_id
                        == template_version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        if set(section_order) != expected:
            raise AssessmentAttemptInvalid("invalid section order")
        return {"section_order": [str(section_id) for section_id in section_order]}

    @staticmethod
    def _attempt_ui_metadata(attempt: AssessmentAttempt) -> dict[str, Any]:
        value = attempt.ui_metadata_json or {}
        order = value.get("section_order", [])
        if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
            return {"section_order": []}
        return {"section_order": order}

    async def submit(
        self, account_id: UUID, attempt_id: UUID, now: datetime
    ) -> dict[str, Any]:
        attempt, assignment = await self._locked_attempt_for_account(
            account_id, attempt_id, now, lock_assignment=True
        )
        if attempt.status == "submitted":
            return dict(attempt.result_json or {})
        self._ensure_draft_mutable(attempt, assignment, now)
        answers = await self._answers(attempt.id)
        await self._validate_answers(
            attempt.template_version_id,
            [
                AnswerInput(
                    row["item_id"], row["answer_type"], row["value"], row["comment"]
                )
                for row in answers
            ],
        )
        items = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItem).where(
                        AssessmentTemplateItem.template_version_id
                        == attempt.template_version_id
                    )
                )
            )
            .scalars()
            .all()
        )
        answered = {row["item_id"] for row in answers}
        required = {item.id for item in items if item.is_required}
        if not required.issubset(answered):
            raise AssessmentAttemptIncomplete("required answers are missing")
        policy = await self._session.get(
            AssessmentScoringPolicy, attempt.template_version_id
        )
        if policy is None:
            result = {
                "scoring_algorithm": "completion_v1",
                "submitted_at": now.isoformat(),
                "answered_count": len(answered),
                "required_count": len(required),
                "total_count": len(items),
            }
        else:
            result = await self._weighted_result(
                attempt,
                assignment,
                items,
                answers,
                policy,
                now,
            )
        attempt.status = "submitted"
        attempt.submitted_at = now
        attempt.result_json = result
        assignment.status = "completed"
        assignment.completed_at = now
        await self._session.flush()
        return result

    async def _weighted_result(
        self,
        attempt: AssessmentAttempt,
        assignment: AssessmentAssignment,
        items: list[AssessmentTemplateItem],
        answers: list[dict[str, Any]],
        policy: AssessmentScoringPolicy,
        now: datetime,
    ) -> dict[str, Any]:
        if policy.algorithm != "weighted_v1" or policy.version != 1:
            raise AssessmentAttemptInvalid("unsupported scoring policy")
        option_rows = (
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
            if items
            else []
        )
        option_values: dict[UUID, dict[UUID, Decimal]] = {}
        for option in option_rows:
            if option.numeric_value is not None:
                option_values.setdefault(option.item_id, {})[
                    option.id
                ] = option.numeric_value
        weighted_items = [
            WeightedItem(
                item_id=item.id,
                answer_type=item.response_type,
                required=item.is_required,
                weight=item.weight,
                min_value=item.min_value,
                max_value=item.max_value,
                criticality=item.criticality,
                config=item.config,
                option_values=option_values.get(item.id, {}),
            )
            for item in items
        ]
        try:
            source_result = calculate_weighted_result(
                weighted_items,
                {row["item_id"]: row["value"] for row in answers},
            )
        except WeightedScoringInvalid as error:
            raise AssessmentAttemptInvalid("invalid weighted assessment") from error

        sections = {
            value.id: value
            for value in (
                await self._session.execute(
                    select(AssessmentTemplateSection).where(
                        AssessmentTemplateSection.template_version_id
                        == attempt.template_version_id
                    )
                )
            )
            .scalars()
            .all()
        }
        weighted_by_id = {value.item_id: value for value in weighted_items}
        answer_values = {row["item_id"]: row["value"] for row in answers}
        section_results = []
        for section in sorted(sections.values(), key=lambda value: value.sort_order):
            section_items = [
                weighted_by_id[item.id]
                for item in items
                if item.section_id == section.id
            ]
            if not section_items:
                continue
            section_answers = {
                item.item_id: answer_values[item.item_id]
                for item in section_items
                if item.item_id in answer_values
            }
            if not section_answers:
                section_results.append(
                    {
                        "section_id": str(section.id),
                        "section_code": section.code,
                        "title": section.title,
                        "score_percent": None,
                        "coverage": "0.000000",
                        "critical_failure_count": 0,
                        "stop_factor_count": 0,
                    }
                )
                continue
            try:
                section_result = calculate_weighted_result(
                    section_items, section_answers
                )
            except WeightedScoringInvalid as error:
                raise AssessmentAttemptInvalid("invalid weighted section") from error
            section_results.append(
                {
                    "section_id": str(section.id),
                    "section_code": section.code,
                    "title": section.title,
                    "score_percent": format(section_result.score_percent, "f"),
                    "coverage": format(section_result.coverage, "f"),
                    "critical_failure_count": section_result.critical_failure_count,
                    "stop_factor_count": section_result.stop_factor_count,
                }
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
                    AssessmentItemMetricMapping.template_version_id
                    == attempt.template_version_id,
                    AssessmentMetricDefinition.status == "active",
                )
            )
        ).all()
        if any(mapping.contribution_weight is None for mapping, _ in mapping_rows):
            raise AssessmentAttemptInvalid("metric mapping weight is unresolved")
        mappings = [
            MetricMapping(
                item_id=mapping.item_id,
                metric_definition_id=definition.id,
                metric_code=definition.code,
                contribution_weight=mapping.contribution_weight,
                direction=mapping.direction,
            )
            for mapping, definition in mapping_rows
            if mapping.contribution_weight is not None
        ]
        try:
            metric_results = calculate_metric_results(source_result, mappings)
        except WeightedScoringInvalid as error:
            raise AssessmentAttemptInvalid("invalid metric mapping") from error

        items_by_id = {value.id: value for value in items}

        def metric_detail(metric) -> dict[str, Any]:
            contributions = []
            for contribution in metric.contributions:
                item_id = UUID(contribution["item_id"])
                item = items_by_id[item_id]
                section = sections[item.section_id]
                contributions.append(
                    {
                        **contribution,
                        "section_id": str(section.id),
                        "section_code": section.code,
                        "item_code": item.code,
                    }
                )
            return {"items": contributions}

        source_type = (
            await self._session.execute(
                select(AssessmentTemplate.activity_type)
                .join(
                    AssessmentTemplateVersion,
                    AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
                )
                .where(AssessmentTemplateVersion.id == attempt.template_version_id)
            )
        ).scalar_one()
        self._session.add_all(
            [
                AssessmentMetricObservation(
                    company_id=assignment.company_id,
                    venue_id=assignment.venue_id,
                    attempt_id=attempt.id,
                    metric_definition_id=metric.metric_definition_id,
                    source_type=source_type,
                    scoring_algorithm=policy.algorithm,
                    scoring_version=policy.version,
                    numerator=metric.numerator,
                    denominator=metric.denominator,
                    score_percent=metric.score_percent,
                    coverage=metric.coverage,
                    status=(
                        "complete"
                        if metric.coverage == Decimal("1")
                        else "insufficient_coverage"
                    ),
                    critical_failure_count=metric.critical_failure_count,
                    stop_factor_count=metric.stop_factor_count,
                    detail_json=metric_detail(metric),
                    observed_at=now,
                )
                for metric in metric_results
            ]
        )
        document = source_result.public_document(now.isoformat())
        document["sections"] = section_results
        return document

    async def result(
        self, account_id: UUID, attempt_id: UUID, now: datetime
    ) -> dict[str, Any]:
        attempt, _ = await self._attempt_for_account(account_id, attempt_id, now)
        if attempt.status != "submitted" or not attempt.result_json:
            raise AssessmentAttemptNotFound("result not found")
        return dict(attempt.result_json)

    async def _authorized(
        self, assignment: AssessmentAssignment, account_id: UUID, now: datetime
    ) -> bool:
        if assignment.purpose == "manager_measurement":
            return assignment.assigned_by_account_id == account_id and await (
                AccessDecisionService(self._session).can_in_company(
                    account_id,
                    assignment.company_id,
                    "assessment.assignment.manage",
                    now,
                )
            )
        profile = (
            await self._session.execute(
                select(EmployeeProfile).where(
                    EmployeeProfile.id == assignment.employee_profile_id,
                    EmployeeProfile.account_id == account_id,
                    EmployeeProfile.company_id == assignment.company_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            return False
        membership = (
            await self._session.execute(
                select(EmployeeAssignment.id)
                .where(
                    EmployeeAssignment.employee_profile_id == profile.id,
                    EmployeeAssignment.company_id == assignment.company_id,
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
        ).scalar_one_or_none()
        return membership is not None

    async def _assignment_for_account(
        self, account_id: UUID, assignment_id: UUID, now: datetime
    ) -> AssessmentAssignment:
        assignment = await self._session.get(AssessmentAssignment, assignment_id)
        if assignment is None or not await self._authorized(
            assignment, account_id, now
        ):
            raise AssessmentAttemptNotFound("assessment not found")
        return assignment

    async def _locked_assignment_for_account(
        self, account_id: UUID, assignment_id: UUID, now: datetime
    ) -> AssessmentAssignment:
        assignment = (
            await self._session.execute(
                select(AssessmentAssignment)
                .where(AssessmentAssignment.id == assignment_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if assignment is None or not await self._authorized(
            assignment, account_id, now
        ):
            raise AssessmentAttemptNotFound("assessment not found")
        return assignment

    async def _attempt_for_account(
        self, account_id: UUID, attempt_id: UUID, now: datetime
    ) -> tuple[AssessmentAttempt, AssessmentAssignment]:
        row = (
            await self._session.execute(
                select(AssessmentAttempt, AssessmentAssignment)
                .join(
                    AssessmentAssignment,
                    AssessmentAttempt.assignment_id == AssessmentAssignment.id,
                )
                .where(
                    AssessmentAttempt.id == attempt_id,
                    AssessmentAttempt.account_id == account_id,
                )
            )
        ).one_or_none()
        if row is None or not await self._authorized(row[1], account_id, now):
            raise AssessmentAttemptNotFound("assessment not found")
        return row[0], row[1]

    async def _locked_attempt_for_account(
        self,
        account_id: UUID,
        attempt_id: UUID,
        now: datetime,
        *,
        lock_assignment: bool = False,
    ) -> tuple[AssessmentAttempt, AssessmentAssignment]:
        attempt = (
            await self._session.execute(
                select(AssessmentAttempt)
                .where(
                    AssessmentAttempt.id == attempt_id,
                    AssessmentAttempt.account_id == account_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if attempt is None:
            raise AssessmentAttemptNotFound("assessment not found")
        query = select(AssessmentAssignment).where(
            AssessmentAssignment.id == attempt.assignment_id
        )
        if lock_assignment:
            query = query.with_for_update()
        assignment = (await self._session.execute(query)).scalar_one()
        if not await self._authorized(assignment, account_id, now):
            raise AssessmentAttemptNotFound("assessment not found")
        return attempt, assignment

    def _ensure_mutable_assignment(
        self, assignment: AssessmentAssignment, now: datetime
    ) -> None:
        if assignment.status in {"revoked", "completed"} or (
            assignment.due_at and assignment.due_at <= now
        ):
            raise AssessmentAttemptReadOnly("assessment is read only")

    def _ensure_draft_mutable(
        self,
        attempt: AssessmentAttempt,
        assignment: AssessmentAssignment,
        now: datetime,
    ) -> None:
        if attempt.status != "draft":
            raise AssessmentAttemptReadOnly("assessment is read only")
        self._ensure_mutable_assignment(assignment, now)

    async def _validate_assignment_template(
        self, assignment: AssessmentAssignment
    ) -> None:
        row = (
            await self._session.execute(
                select(AssessmentTemplateVersion, AssessmentTemplate)
                .join(
                    AssessmentTemplate,
                    AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
                )
                .where(
                    AssessmentTemplateVersion.id == assignment.template_version_id,
                    AssessmentTemplateVersion.status == "published",
                    AssessmentTemplate.status == "active",
                    AssessmentTemplate.deleted_at.is_(None),
                    AssessmentTemplate.scope == "company",
                    AssessmentTemplate.company_id == assignment.company_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise AssessmentAttemptNotFound("assessment not found")

    async def _validate_answers(
        self, template_version_id: UUID, answers: list[AnswerInput]
    ) -> list[dict[str, Any]]:
        if len(answers) > MAX_ANSWERS:
            raise AssessmentAttemptInvalid("too many answers")
        if len({answer.item_id for answer in answers}) != len(answers):
            raise AssessmentAttemptInvalid("duplicate item")
        items = {
            item.id: item
            for item in (
                await self._session.execute(
                    select(AssessmentTemplateItem).where(
                        AssessmentTemplateItem.template_version_id
                        == template_version_id
                    )
                )
            )
            .scalars()
            .all()
        }
        option_rows = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItemOption).where(
                        AssessmentTemplateItemOption.item_id.in_(items.keys())
                    )
                )
            )
            .scalars()
            .all()
            if items
            else []
        )
        options: dict[UUID, set[UUID]] = {}
        for option in option_rows:
            options.setdefault(option.item_id, set()).add(option.id)
        normalized = []
        for answer in answers:
            item = items.get(answer.item_id)
            if item is None or answer.answer_type != item.response_type:
                raise AssessmentAttemptInvalid("invalid assessment answer")
            value = self._normalize_value(
                answer.answer_type, answer.value, options.get(answer.item_id, set())
            )
            if value is not None:
                comment = answer.comment.strip() if answer.comment else None
                if comment and len(comment) > MAX_TEXT_LENGTH:
                    raise AssessmentAttemptInvalid("comment too long")
                needs_comment = item.evidence_mode == "required_comment" or (
                    bool(item.config.get("comment_on_negative"))
                    and self._is_negative(item, value)
                )
                if needs_comment and not comment:
                    raise AssessmentAttemptInvalid("comment is required")
                normalized.append(
                    {
                        "item_id": answer.item_id,
                        "answer_type": answer.answer_type,
                        "value": value,
                        "comment": comment,
                    }
                )
        try:
            encoded = json.dumps(
                normalized, default=str, allow_nan=False, separators=(",", ":")
            ).encode()
        except (TypeError, ValueError) as error:
            raise AssessmentAttemptInvalid("invalid assessment answer") from error
        if len(encoded) > MAX_DOCUMENT_BYTES:
            raise AssessmentAttemptInvalid("assessment document too large")
        return normalized

    def _normalize_value(
        self, answer_type: str, value: Any, allowed_options: set[UUID]
    ) -> Any:
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
                parsed = (
                    date.fromisoformat(value)
                    if answer_type == "date"
                    else time.fromisoformat(value)
                )
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
            if len(set(selected)) != len(selected) or not set(selected).issubset(
                allowed_options
            ):
                raise AssessmentAttemptInvalid("invalid options")
            return [str(option) for option in selected]
        raise AssessmentAttemptInvalid("unsupported answer type")

    async def _answers(self, attempt_id: UUID) -> list[dict[str, Any]]:
        rows = (
            (
                await self._session.execute(
                    select(AssessmentAttemptAnswer)
                    .where(AssessmentAttemptAnswer.attempt_id == attempt_id)
                    .order_by(AssessmentAttemptAnswer.item_id)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                "item_id": row.item_id,
                "answer_type": row.answer_type,
                "value": row.value_json,
                "comment": row.comment,
            }
            for row in rows
        ]

    @staticmethod
    def _is_negative(item: AssessmentTemplateItem, value: Any) -> bool:
        if item.response_type == "boolean":
            return value is False
        threshold = item.passing_value
        if threshold is None:
            threshold = item.config.get("critical_threshold")
        if threshold is None or item.response_type not in {
            "score",
            "integer",
            "decimal",
        }:
            return False
        try:
            return Decimal(str(value)) < Decimal(str(threshold))
        except (InvalidOperation, ValueError):
            return False

    async def _template_document(self, version_id: UUID) -> dict[str, Any]:
        sections = (
            (
                await self._session.execute(
                    select(AssessmentTemplateSection)
                    .where(AssessmentTemplateSection.template_version_id == version_id)
                    .order_by(
                        AssessmentTemplateSection.sort_order,
                        AssessmentTemplateSection.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        items = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItem)
                    .where(AssessmentTemplateItem.template_version_id == version_id)
                    .order_by(
                        AssessmentTemplateItem.sort_order, AssessmentTemplateItem.id
                    )
                )
            )
            .scalars()
            .all()
        )
        options = (
            (
                await self._session.execute(
                    select(AssessmentTemplateItemOption)
                    .where(
                        AssessmentTemplateItemOption.item_id.in_(
                            [item.id for item in items]
                        )
                    )
                    .order_by(
                        AssessmentTemplateItemOption.sort_order,
                        AssessmentTemplateItemOption.id,
                    )
                )
            )
            .scalars()
            .all()
            if items
            else []
        )
        by_item: dict[UUID, list[dict[str, Any]]] = {}
        for option in options:
            by_item.setdefault(option.item_id, []).append(
                {
                    "id": option.id,
                    "label": option.label,
                    "sort_order": option.sort_order,
                }
            )
        by_section: dict[UUID, list[dict[str, Any]]] = {}
        for item in items:
            safe_config = {
                key: value
                for key, value in item.config.items()
                if key in {"placeholder", "max_length", "critical_threshold"}
            }
            by_section.setdefault(item.section_id, []).append(
                {
                    "id": item.id,
                    "prompt": item.prompt,
                    "guidance": item.guidance,
                    "answer_type": item.response_type,
                    "required": item.is_required,
                    "sort_order": item.sort_order,
                    "weight": str(item.weight) if item.weight is not None else None,
                    "min_value": (
                        str(item.min_value) if item.min_value is not None else None
                    ),
                    "max_value": (
                        str(item.max_value) if item.max_value is not None else None
                    ),
                    "passing_value": (
                        str(item.passing_value)
                        if item.passing_value is not None
                        else None
                    ),
                    "evidence_mode": item.evidence_mode,
                    "criticality": item.criticality,
                    "config": safe_config,
                    "options": by_item.get(item.id, []),
                }
            )
        return {
            "version_id": version_id,
            "sections": [
                {
                    "id": section.id,
                    "parent_section_id": section.parent_section_id,
                    "title": section.title,
                    "description": section.description,
                    "sort_order": section.sort_order,
                    "items": by_section.get(section.id, []),
                }
                for section in sections
            ],
        }

    async def _assignment_document(
        self, assignment: AssessmentAssignment, now: datetime
    ) -> dict[str, Any]:
        await self._validate_assignment_template(assignment)
        version, template = (
            await self._session.execute(
                select(AssessmentTemplateVersion, AssessmentTemplate)
                .join(
                    AssessmentTemplate,
                    AssessmentTemplateVersion.template_id == AssessmentTemplate.id,
                )
                .where(AssessmentTemplateVersion.id == assignment.template_version_id)
            )
        ).one()
        result = self._assignment_summary(assignment, template, version, now)
        result["document"] = await self._template_document(version.id)
        return result

    def _assignment_summary(
        self,
        assignment: AssessmentAssignment,
        template: AssessmentTemplate,
        version: AssessmentTemplateVersion,
        now: datetime,
        submitted_at: datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "id": assignment.id,
            "company_id": assignment.company_id,
            "venue_id": assignment.venue_id,
            "status": assignment.status,
            "assigned_at": assignment.assigned_at,
            "due_at": assignment.due_at,
            "submitted_at": submitted_at,
            "template_name": template.name,
            "template_version": version.version,
            "read_only": assignment.status in {"revoked", "completed"}
            or bool(assignment.due_at and assignment.due_at <= now),
        }

    async def _attempt_document(
        self,
        attempt: AssessmentAttempt,
        assignment: AssessmentAssignment,
        now: datetime,
    ) -> dict[str, Any]:
        reason = None
        if attempt.status == "submitted":
            reason = "submitted"
        elif assignment.status == "revoked":
            reason = "revoked"
        elif assignment.due_at and assignment.due_at <= now:
            reason = "expired"
        return {
            "id": attempt.id,
            "assignment_id": assignment.id,
            "status": attempt.status,
            "revision": attempt.revision,
            "started_at": attempt.started_at,
            "last_saved_at": attempt.last_saved_at,
            "submitted_at": attempt.submitted_at,
            "read_only": reason is not None,
            "read_only_reason": reason,
            "document": await self._template_document(attempt.template_version_id),
            "answers": await self._answers(attempt.id),
            "ui_metadata": self._attempt_ui_metadata(attempt),
        }
