"""Account-scoped immutable assessment history and result projections."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Date, and_, case, cast, exists, func, literal, or_, select
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
    Company,
    EmployeeAssignment,
    EmployeeProfile,
    Task,
    TaskAssignment,
    Venue,
)
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.presentation_percent import format_percent


READ_PERMISSION = "assessment.assignment.read"
MANAGE_PERMISSION = "assessment.assignment.manage"
MAX_HISTORY_LIMIT = 100
MAX_CURSOR_BYTES = 256


class AssessmentHistoryInvalid(Exception):
    pass


class AssessmentHistoryNotFound(Exception):
    pass


@dataclass(frozen=True)
class HistoryPageQuery:
    account_id: UUID
    company_id: UUID
    now: datetime
    period: str = "all"
    date_from: date | None = None
    date_to: date | None = None
    cursor: str | None = None
    limit: int = 30


@dataclass(frozen=True)
class _DecodedCursor:
    event_at: datetime
    attempt_id: UUID


class AssessmentHistoryService:
    """Read-only service; callers own the session lifecycle."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._access = AccessDecisionService(session)

    async def history(self, query: HistoryPageQuery) -> dict[str, Any]:
        now = self._aware(query.now, "now")
        if not 1 <= query.limit <= MAX_HISTORY_LIMIT:
            raise AssessmentHistoryInvalid("history limit is invalid")
        company = await self._company(query.company_id)
        cursor = self._decode_cursor(query.cursor) if query.cursor else None

        event_at = self._event_at_expression()
        timezone_name = func.coalesce(Venue.timezone, Company.timezone)
        local_event_date = cast(func.timezone(timezone_name, event_at), Date)
        local_now = func.timezone(timezone_name, literal(now))
        local_today = cast(local_now, Date)

        authorization = await self._history_authorization(
            query.account_id, query.company_id, now
        )
        statement = (
            select(
                AssessmentAttempt,
                AssessmentAssignment,
                AssessmentTemplate,
                AssessmentTemplateVersion,
                EmployeeProfile,
                Venue,
                Company,
                event_at.label("event_at"),
            )
            .join(
                AssessmentAssignment,
                AssessmentAssignment.id == AssessmentAttempt.assignment_id,
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
            .join(
                EmployeeProfile,
                EmployeeProfile.id == AssessmentAssignment.employee_profile_id,
            )
            .join(Company, Company.id == AssessmentAssignment.company_id)
            .outerjoin(Venue, Venue.id == AssessmentAssignment.venue_id)
            .where(
                AssessmentAssignment.company_id == query.company_id,
                or_(
                    AssessmentAttempt.status == "submitted",
                    AssessmentAssignment.revoked_at.is_not(None),
                    and_(
                        AssessmentAssignment.due_at.is_not(None),
                        AssessmentAssignment.due_at <= now,
                    ),
                ),
                event_at.is_not(None),
                authorization,
            )
        )
        statement = statement.where(
            self._period_predicate(
                query.period,
                query.date_from,
                query.date_to,
                local_event_date,
                local_today,
                local_now,
            )
        )
        if cursor is not None:
            statement = statement.where(
                or_(
                    event_at < cursor.event_at,
                    and_(
                        event_at == cursor.event_at,
                        AssessmentAttempt.id < cursor.attempt_id,
                    ),
                )
            )
        rows = (
            await self._session.execute(
                statement.order_by(event_at.desc(), AssessmentAttempt.id.desc()).limit(
                    query.limit + 1
                )
            )
        ).all()
        page_rows = rows[: query.limit]
        items = [self._history_item(row, now) for row in page_rows]
        next_cursor = None
        if len(rows) > query.limit and page_rows:
            last = page_rows[-1]
            next_cursor = self._encode_cursor(last.event_at, last.AssessmentAttempt.id)
        return {
            "items": items,
            "next_cursor": next_cursor,
            "company_timezone": company.timezone,
        }

    async def result_projection(
        self,
        account_id: UUID,
        company_id: UUID,
        attempt_id: UUID,
        now: datetime,
    ) -> dict[str, Any]:
        checked_now = self._aware(now, "now")
        row = (
            await self._session.execute(
                select(
                    AssessmentAttempt,
                    AssessmentAssignment,
                    AssessmentTemplate,
                    AssessmentTemplateVersion,
                    EmployeeProfile,
                    Venue,
                    Company,
                )
                .join(
                    AssessmentAssignment,
                    AssessmentAssignment.id == AssessmentAttempt.assignment_id,
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
                .join(
                    EmployeeProfile,
                    EmployeeProfile.id == AssessmentAssignment.employee_profile_id,
                )
                .join(Company, Company.id == AssessmentAssignment.company_id)
                .outerjoin(Venue, Venue.id == AssessmentAssignment.venue_id)
                .where(
                    AssessmentAttempt.id == attempt_id,
                    AssessmentAssignment.company_id == company_id,
                )
            )
        ).one_or_none()
        if row is None or row.AssessmentAttempt.status != "submitted":
            raise AssessmentHistoryNotFound("assessment result not found")
        if not await self._can_read_result(row, account_id, checked_now):
            raise AssessmentHistoryNotFound("assessment result not found")
        if not row.AssessmentAttempt.result_json:
            raise AssessmentHistoryNotFound("assessment result not found")

        sections = await self._result_sections(
            row.AssessmentAttempt.template_version_id,
            row.AssessmentAttempt.id,
            row.AssessmentAttempt.result_json,
        )
        timezone_name = (
            row.Venue.timezone
            if row.Venue and row.Venue.timezone
            else row.Company.timezone
        )
        local_submitted = self._local_datetime(
            row.AssessmentAttempt.submitted_at, timezone_name
        )
        result = dict(row.AssessmentAttempt.result_json)
        return {
            "attempt_id": row.AssessmentAttempt.id,
            "company_id": row.AssessmentAssignment.company_id,
            "venue_id": row.AssessmentAssignment.venue_id,
            "template_name": row.AssessmentTemplate.name,
            "template_version": row.AssessmentTemplateVersion.version,
            "status": "completed",
            "venue_name": row.Venue.name if row.Venue else None,
            "subject_name": row.EmployeeProfile.full_name,
            "submitted_at": row.AssessmentAttempt.submitted_at,
            "local_submitted_at": local_submitted.isoformat(),
            "timezone": timezone_name,
            "scoring_algorithm": result.get("scoring_algorithm"),
            "score_percent": result.get("score_percent"),
            "score_display": (
                format_percent(result["score_percent"])
                if result.get("score_percent") is not None
                else None
            ),
            "answered_count": int(result.get("answered_count", 0)),
            "required_count": int(result.get("required_count", 0)),
            "total_count": int(result.get("total_count", 0)),
            "critical_failure_count": int(result.get("critical_failure_count", 0) or 0),
            "stop_factor_count": int(result.get("stop_factor_count", 0) or 0),
            "sections": sections,
            "related_tasks": await self._related_tasks(
                account_id, company_id, attempt_id
            ),
        }

    async def _company(self, company_id: UUID) -> Company:
        value = (
            await self._session.execute(
                select(Company).where(
                    Company.id == company_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if value is None:
            raise AssessmentHistoryNotFound("assessment history not found")
        try:
            ZoneInfo(value.timezone)
        except ZoneInfoNotFoundError as error:
            raise AssessmentHistoryInvalid("company timezone is invalid") from error
        return value

    async def _history_authorization(
        self, account_id: UUID, company_id: UUID, now: datetime
    ):
        company_wide = await self._access.can_in_company(
            account_id, company_id, READ_PERMISSION, now
        ) or await self._access.can_in_company(
            account_id, company_id, MANAGE_PERMISSION, now
        )
        if company_wide:
            return literal(True)
        venue_ids = await self._access.list_accessible_venue_ids(
            account_id, company_id, READ_PERMISSION, now
        ) | await self._access.list_accessible_venue_ids(
            account_id, company_id, MANAGE_PERMISSION, now
        )
        active_membership = exists(
            select(EmployeeAssignment.id).where(
                EmployeeAssignment.employee_profile_id == EmployeeProfile.id,
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.status == "active",
                EmployeeAssignment.starts_at <= now,
                or_(
                    EmployeeAssignment.ends_at.is_(None),
                    EmployeeAssignment.ends_at > now,
                ),
                EmployeeAssignment.deleted_at.is_(None),
            )
        )
        self_access = and_(
            EmployeeProfile.account_id == account_id,
            EmployeeProfile.employment_status == "active",
            EmployeeProfile.deleted_at.is_(None),
            active_membership,
        )
        if not venue_ids:
            return self_access
        return or_(self_access, AssessmentAssignment.venue_id.in_(venue_ids))

    async def _can_read_result(self, row, account_id: UUID, now: datetime) -> bool:
        if row.EmployeeProfile.account_id == account_id:
            membership = (
                await self._session.execute(
                    select(EmployeeAssignment.id)
                    .where(
                        EmployeeAssignment.employee_profile_id
                        == row.EmployeeProfile.id,
                        EmployeeAssignment.company_id
                        == row.AssessmentAssignment.company_id,
                        EmployeeAssignment.status == "active",
                        EmployeeAssignment.starts_at <= now,
                        or_(
                            EmployeeAssignment.ends_at.is_(None),
                            EmployeeAssignment.ends_at > now,
                        ),
                        EmployeeAssignment.deleted_at.is_(None),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if membership is not None:
                return True
        employee_allowed = await self._access.can_for_employee(
            account_id,
            row.AssessmentAssignment.company_id,
            READ_PERMISSION,
            row.EmployeeProfile.id,
            now,
        ) or await self._access.can_for_employee(
            account_id,
            row.AssessmentAssignment.company_id,
            MANAGE_PERMISSION,
            row.EmployeeProfile.id,
            now,
        )
        if not employee_allowed:
            return False
        if row.AssessmentAssignment.venue_id is None:
            return await self._access.can_in_company(
                account_id,
                row.AssessmentAssignment.company_id,
                READ_PERMISSION,
                now,
            ) or await self._access.can_in_company(
                account_id,
                row.AssessmentAssignment.company_id,
                MANAGE_PERMISSION,
                now,
            )
        return await self._access.can_for_venue(
            account_id,
            row.AssessmentAssignment.company_id,
            READ_PERMISSION,
            row.AssessmentAssignment.venue_id,
            now,
        ) or await self._access.can_for_venue(
            account_id,
            row.AssessmentAssignment.company_id,
            MANAGE_PERMISSION,
            row.AssessmentAssignment.venue_id,
            now,
        )

    async def _result_sections(
        self, template_version_id: UUID, attempt_id: UUID, result: dict[str, Any]
    ) -> list[dict[str, Any]]:
        sections = (
            (
                await self._session.execute(
                    select(AssessmentTemplateSection)
                    .where(
                        AssessmentTemplateSection.template_version_id
                        == template_version_id
                    )
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
                    .where(
                        AssessmentTemplateItem.template_version_id
                        == template_version_id
                    )
                    .order_by(
                        AssessmentTemplateItem.sort_order, AssessmentTemplateItem.id
                    )
                )
            )
            .scalars()
            .all()
        )
        answers = (
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
            if items
            else []
        )
        option_labels = {option.id: option.label for option in options}
        answers_by_item = {answer.item_id: answer for answer in answers}
        score_by_section = {
            str(section.get("section_id")): section
            for section in result.get("sections", [])
            if isinstance(section, dict)
        }
        projected: list[dict[str, Any]] = []
        for section in sections:
            score = score_by_section.get(str(section.id), {})
            projected_items = []
            for item in items:
                if item.section_id != section.id:
                    continue
                answer = answers_by_item.get(item.id)
                if answer is None:
                    continue
                projected_items.append(
                    {
                        "prompt": item.prompt,
                        "answer_type": answer.answer_type,
                        "value": self._display_answer(
                            answer.answer_type, answer.value_json, option_labels
                        ),
                        "comment": answer.comment,
                    }
                )
            raw_score = score.get("score_percent")
            projected.append(
                {
                    "title": section.title,
                    "score_percent": raw_score,
                    "score_display": (
                        format_percent(raw_score) if raw_score is not None else None
                    ),
                    "coverage": score.get("coverage"),
                    "critical_failure_count": int(
                        score.get("critical_failure_count", 0) or 0
                    ),
                    "stop_factor_count": int(score.get("stop_factor_count", 0) or 0),
                    "items": projected_items,
                }
            )
        return projected

    async def _related_tasks(
        self, account_id: UUID, company_id: UUID, attempt_id: UUID
    ) -> list[dict[str, str]]:
        profile_ids = select(EmployeeProfile.id).where(
            EmployeeProfile.account_id == account_id,
            EmployeeProfile.company_id == company_id,
            EmployeeProfile.deleted_at.is_(None),
        )
        rows = (
            await self._session.execute(
                select(Task.id, Task.title, Task.status, Task.created_at)
                .outerjoin(
                    TaskAssignment,
                    and_(
                        TaskAssignment.task_id == Task.id,
                        TaskAssignment.company_id == Task.company_id,
                    ),
                )
                .where(
                    Task.company_id == company_id,
                    Task.assessment_attempt_id == attempt_id,
                    or_(
                        Task.author_account_id == account_id,
                        TaskAssignment.employee_profile_id.in_(profile_ids),
                    ),
                )
                .distinct()
                .order_by(Task.created_at, Task.id)
            )
        ).all()
        return [{"title": row.title, "status": row.status} for row in rows]

    @staticmethod
    def _display_answer(
        answer_type: str, value: Any, option_labels: dict[UUID, str]
    ) -> Any:
        if answer_type == "boolean":
            return "Да" if value is True else "Нет"
        if answer_type == "single_choice":
            try:
                return option_labels.get(UUID(str(value)), "Недоступный вариант")
            except (TypeError, ValueError):
                return "Недоступный вариант"
        if answer_type == "multi_choice":
            if not isinstance(value, list):
                return []
            labels = []
            for entry in value:
                try:
                    labels.append(
                        option_labels.get(UUID(str(entry)), "Недоступный вариант")
                    )
                except (TypeError, ValueError):
                    labels.append("Недоступный вариант")
            return labels
        return value

    @staticmethod
    def _event_at_expression():
        return case(
            (
                AssessmentAttempt.submitted_at.is_not(None),
                AssessmentAttempt.submitted_at,
            ),
            (
                AssessmentAssignment.revoked_at.is_not(None),
                AssessmentAssignment.revoked_at,
            ),
            else_=AssessmentAssignment.due_at,
        )

    @staticmethod
    def _period_predicate(
        period: str,
        date_from: date | None,
        date_to: date | None,
        local_event_date,
        local_today,
        local_now,
    ):
        if period == "all":
            if date_from is not None or date_to is not None:
                raise AssessmentHistoryInvalid("all-time history has no date bounds")
            return literal(True)
        if period == "yesterday":
            return local_event_date == cast(local_today - literal(1), Date)
        if period == "previous_week":
            week_start = cast(func.date_trunc("week", local_now), Date)
            return and_(
                local_event_date >= cast(week_start - literal(7), Date),
                local_event_date < week_start,
            )
        if period == "previous_month":
            month_start = cast(func.date_trunc("month", local_now), Date)
            previous_start = cast(
                func.date_trunc("month", local_now - func.make_interval(0, 1)),
                Date,
            )
            return and_(
                local_event_date >= previous_start,
                local_event_date < month_start,
            )
        if period == "custom":
            if date_from is None or date_to is None:
                raise AssessmentHistoryInvalid("custom history bounds are required")
            if date_from > date_to or date_to - date_from > timedelta(days=366):
                raise AssessmentHistoryInvalid("custom history bounds are invalid")
            return and_(
                local_event_date >= date_from,
                local_event_date <= date_to,
            )
        raise AssessmentHistoryInvalid("history period is invalid")

    @classmethod
    def _history_item(cls, row, now: datetime) -> dict[str, Any]:
        timezone_name = (
            row.Venue.timezone
            if row.Venue and row.Venue.timezone
            else row.Company.timezone
        )
        local_event = cls._local_datetime(row.event_at, timezone_name)
        local_today = cls._local_datetime(now, timezone_name).date()
        result = row.AssessmentAttempt.result_json or {}
        if row.AssessmentAttempt.status == "submitted":
            status = "completed"
        elif row.AssessmentAssignment.revoked_at is not None:
            status = "revoked"
        elif row.AssessmentAssignment.due_at and row.AssessmentAssignment.due_at <= now:
            status = "expired"
        else:
            status = "unavailable"
        raw_score = result.get("score_percent")
        return {
            "attempt_id": row.AssessmentAttempt.id,
            "template_name": row.AssessmentTemplate.name,
            "template_version": row.AssessmentTemplateVersion.version,
            "status": status,
            "event_at": row.event_at,
            "local_event_at": local_event.isoformat(),
            "local_date": local_event.date(),
            "day_label": cls._day_label(local_event.date(), local_today),
            "timezone": timezone_name,
            "venue_name": row.Venue.name if row.Venue else None,
            "subject_name": row.EmployeeProfile.full_name,
            "score_percent": raw_score,
            "score_display": (
                format_percent(raw_score) if raw_score is not None else None
            ),
            "has_result": row.AssessmentAttempt.status == "submitted" and bool(result),
            "pdf_available": row.AssessmentAttempt.status == "submitted"
            and bool(result),
        }

    @staticmethod
    def _day_label(value: date, today: date) -> str:
        months = (
            "января",
            "февраля",
            "марта",
            "апреля",
            "мая",
            "июня",
            "июля",
            "августа",
            "сентября",
            "октября",
            "ноября",
            "декабря",
        )
        suffix = f"{value.day} {months[value.month - 1]}"
        if value == today:
            return f"Сегодня, {suffix}"
        if value == today - timedelta(days=1):
            return f"Вчера, {suffix}"
        if value.year != today.year:
            return f"{suffix} {value.year}"
        return suffix

    @staticmethod
    def _local_datetime(value: datetime, timezone_name: str) -> datetime:
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise AssessmentHistoryInvalid("assessment timezone is invalid") from error
        return value.astimezone(local_timezone)

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise AssessmentHistoryInvalid(f"{name} must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _encode_cursor(event_at: datetime, attempt_id: UUID) -> str:
        payload = json.dumps(
            {"event_at": event_at.isoformat(), "attempt_id": str(attempt_id)},
            separators=(",", ":"),
        ).encode("ascii")
        return urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(value: str) -> _DecodedCursor:
        if not value or len(value.encode("utf-8")) > MAX_CURSOR_BYTES:
            raise AssessmentHistoryInvalid("history cursor is invalid")
        try:
            padding = "=" * (-len(value) % 4)
            payload = json.loads(urlsafe_b64decode(value + padding))
            if set(payload) != {"event_at", "attempt_id"}:
                raise ValueError
            event_at = datetime.fromisoformat(payload["event_at"])
            if event_at.tzinfo is None or event_at.utcoffset() is None:
                raise ValueError
            attempt_id = UUID(payload["attempt_id"])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise AssessmentHistoryInvalid("history cursor is invalid") from error
        return _DecodedCursor(event_at.astimezone(timezone.utc), attempt_id)
