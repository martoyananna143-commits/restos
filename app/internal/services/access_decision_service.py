"""Read-only access decisions for the additive account architecture."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue


_PERMISSION_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,2}$"
)
_SCOPE_RANK = {
    "self": 0,
    "working_venues": 1,
    "explicit_venues": 2,
    "company": 3,
}


class _EligibleAssignment(NamedTuple):
    id: UUID
    employee_profile_id: UUID
    scope_type: str


class AccessDecisionService:
    """Evaluate additive access rules without mutating state."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def can_in_company(
        self,
        account_id: UUID,
        company_id: UUID,
        permission_code: str,
        now: datetime | None = None,
    ) -> bool:
        """Return whether an account has company-wide permission in a company."""
        checked_now = self._validate_inputs(
            account_id, company_id, permission_code, now
        )
        if not await self._account_is_active(account_id):
            return False
        owner_id = await self._active_company_owner_id(company_id)
        if owner_id is None:
            return False
        if owner_id == account_id:
            return True
        assignments = await self._eligible_assignments(
            account_id, company_id, permission_code, checked_now
        )
        return any(
            assignment.scope_type == "company" for assignment in assignments
        )

    async def can_for_venue(
        self,
        account_id: UUID,
        company_id: UUID,
        permission_code: str,
        venue_id: UUID,
        now: datetime | None = None,
    ) -> bool:
        """Return whether one assignment covers a valid venue."""
        self._require_uuid("venue_id", venue_id)
        checked_now = self._validate_inputs(
            account_id, company_id, permission_code, now
        )
        if not await self._account_is_active(account_id):
            return False
        owner_id = await self._active_company_owner_id(company_id)
        if owner_id is None or not await self._venue_is_available(
            company_id, venue_id
        ):
            return False
        if owner_id == account_id:
            return True

        assignments = await self._eligible_assignments(
            account_id, company_id, permission_code, checked_now
        )
        for assignment in assignments:
            if assignment.scope_type == "company":
                return True
            if assignment.scope_type == "working_venues":
                if await self._assignment_contains_venue(
                    AssignmentVenue, assignment.id, company_id, venue_id
                ):
                    return True
            elif assignment.scope_type == "explicit_venues":
                if await self._assignment_contains_venue(
                    AssignmentScopeVenue, assignment.id, company_id, venue_id
                ):
                    return True
        return False

    async def can_for_employee(
        self,
        account_id: UUID,
        company_id: UUID,
        permission_code: str,
        employee_profile_id: UUID,
        now: datetime | None = None,
    ) -> bool:
        """Return whether one assignment covers a company employee profile."""
        self._require_uuid("employee_profile_id", employee_profile_id)
        checked_now = self._validate_inputs(
            account_id, company_id, permission_code, now
        )
        if not await self._account_is_active(account_id):
            return False
        owner_id = await self._active_company_owner_id(company_id)
        if owner_id is None or not await self._employee_exists(
            company_id, employee_profile_id
        ):
            return False
        if owner_id == account_id:
            return True

        assignments = await self._eligible_assignments(
            account_id, company_id, permission_code, checked_now
        )
        for assignment in assignments:
            if assignment.scope_type == "company":
                return True
            if (
                assignment.scope_type == "self"
                and assignment.employee_profile_id == employee_profile_id
            ):
                return True
            if assignment.scope_type in {"working_venues", "explicit_venues"}:
                venue_ids = await self._assignment_venue_ids(
                    assignment, company_id
                )
                if venue_ids and await self._employee_works_in_any_venue(
                    employee_profile_id,
                    company_id,
                    venue_ids,
                    checked_now,
                ):
                    return True
        return False

    async def list_accessible_venue_ids(
        self,
        account_id: UUID,
        company_id: UUID,
        permission_code: str,
        now: datetime | None = None,
    ) -> set[UUID]:
        """Return unique valid venue IDs covered by qualifying assignments."""
        checked_now = self._validate_inputs(
            account_id, company_id, permission_code, now
        )
        if not await self._account_is_active(account_id):
            return set()
        owner_id = await self._active_company_owner_id(company_id)
        if owner_id is None:
            return set()

        available_ids = await self._available_venue_ids(company_id)
        if owner_id == account_id:
            return available_ids

        assignments = await self._eligible_assignments(
            account_id, company_id, permission_code, checked_now
        )
        result: set[UUID] = set()
        for assignment in assignments:
            if assignment.scope_type == "company":
                result.update(available_ids)
            elif assignment.scope_type != "self":
                result.update(
                    await self._assignment_venue_ids(assignment, company_id)
                )
        return result & available_ids

    @staticmethod
    def _require_uuid(name: str, value: UUID) -> None:
        if not isinstance(value, UUID):
            raise ValueError(f"{name} must be a UUID")

    @classmethod
    def _validate_inputs(
        cls,
        account_id: UUID,
        company_id: UUID,
        permission_code: str,
        now: datetime | None,
    ) -> datetime:
        cls._require_uuid("account_id", account_id)
        cls._require_uuid("company_id", company_id)
        if not isinstance(permission_code, str) or not _PERMISSION_RE.fullmatch(
            permission_code
        ):
            raise ValueError("permission_code has an invalid format")
        checked_now = now or datetime.now(timezone.utc)
        if checked_now.tzinfo is None or checked_now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return checked_now

    async def _active_company_owner_id(self, company_id: UUID) -> UUID | None:
        statement = select(Company.owner_account_id).where(
            Company.id == company_id,
            Company.status == "active",
            Company.deleted_at.is_(None),
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _account_is_active(self, account_id: UUID) -> bool:
        statement = select(Account.id).where(
            Account.id == account_id,
            Account.status == "active",
            Account.deleted_at.is_(None),
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def _eligible_assignments(
        self,
        account_id: UUID,
        company_id: UUID,
        permission_code: str,
        now: datetime,
    ) -> list[_EligibleAssignment]:
        statement = (
            select(
                EmployeeAssignment.id,
                EmployeeAssignment.employee_profile_id,
                EmployeeAssignment.scope_type,
                AccessProfile.maximum_scope,
            )
            .join(
                EmployeeProfile,
                (EmployeeProfile.id == EmployeeAssignment.employee_profile_id)
                & (EmployeeProfile.company_id == EmployeeAssignment.company_id),
            )
            .join(
                Position,
                (Position.id == EmployeeAssignment.position_id)
                & (Position.company_id == EmployeeAssignment.company_id),
            )
            .join(
                AccessProfile,
                (AccessProfile.id == EmployeeAssignment.access_profile_id)
                & (AccessProfile.company_id == EmployeeAssignment.company_id),
            )
            .join(
                AccessProfilePermission,
                AccessProfilePermission.access_profile_id == AccessProfile.id,
            )
            .where(
                EmployeeProfile.account_id == account_id,
                EmployeeProfile.company_id == company_id,
                EmployeeProfile.employment_status == "active",
                EmployeeProfile.deleted_at.is_(None),
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.status == "active",
                EmployeeAssignment.deleted_at.is_(None),
                EmployeeAssignment.starts_at <= now,
                (EmployeeAssignment.ends_at.is_(None))
                | (EmployeeAssignment.ends_at > now),
                Position.company_id == company_id,
                Position.is_active.is_(True),
                Position.deleted_at.is_(None),
                AccessProfile.company_id == company_id,
                AccessProfile.is_active.is_(True),
                AccessProfile.deleted_at.is_(None),
                AccessProfilePermission.permission_code == permission_code,
            )
        )
        rows = (await self._session.execute(statement)).all()
        return [
            _EligibleAssignment(row.id, row.employee_profile_id, row.scope_type)
            for row in rows
            if self._scope_allowed(row.scope_type, row.maximum_scope)
        ]

    @staticmethod
    def _scope_allowed(scope_type: str, maximum_scope: str) -> bool:
        scope_rank = _SCOPE_RANK.get(scope_type)
        maximum_rank = _SCOPE_RANK.get(maximum_scope)
        return (
            scope_rank is not None
            and maximum_rank is not None
            and scope_rank <= maximum_rank
        )

    async def _venue_is_available(
        self, company_id: UUID, venue_id: UUID
    ) -> bool:
        statement = select(Venue.id).where(
            Venue.id == venue_id,
            Venue.company_id == company_id,
            Venue.deleted_at.is_(None),
            Venue.status != "closed",
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def _employee_exists(
        self, company_id: UUID, employee_profile_id: UUID
    ) -> bool:
        statement = select(EmployeeProfile.id).where(
            EmployeeProfile.id == employee_profile_id,
            EmployeeProfile.company_id == company_id,
            EmployeeProfile.deleted_at.is_(None),
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def _assignment_contains_venue(
        self,
        association: type[AssignmentVenue] | type[AssignmentScopeVenue],
        assignment_id: UUID,
        company_id: UUID,
        venue_id: UUID,
    ) -> bool:
        statement = select(association.venue_id).where(
            association.assignment_id == assignment_id,
            association.company_id == company_id,
            association.venue_id == venue_id,
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def _assignment_venue_ids(
        self,
        assignment: _EligibleAssignment,
        company_id: UUID,
    ) -> set[UUID]:
        association = (
            AssignmentVenue
            if assignment.scope_type == "working_venues"
            else AssignmentScopeVenue
        )
        statement = select(association.venue_id).where(
            association.assignment_id == assignment.id,
            association.company_id == company_id,
        )
        return set((await self._session.execute(statement)).scalars())

    async def _available_venue_ids(self, company_id: UUID) -> set[UUID]:
        statement = select(Venue.id).where(
            Venue.company_id == company_id,
            Venue.deleted_at.is_(None),
            Venue.status != "closed",
        )
        return set((await self._session.execute(statement)).scalars())

    async def _employee_works_in_any_venue(
        self,
        employee_profile_id: UUID,
        company_id: UUID,
        venue_ids: set[UUID],
        now: datetime,
    ) -> bool:
        statement: Select[tuple[UUID]] = (
            select(AssignmentVenue.venue_id)
            .join(
                EmployeeAssignment,
                (EmployeeAssignment.id == AssignmentVenue.assignment_id)
                & (EmployeeAssignment.company_id == AssignmentVenue.company_id),
            )
            .where(
                EmployeeAssignment.employee_profile_id == employee_profile_id,
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.status == "active",
                EmployeeAssignment.deleted_at.is_(None),
                EmployeeAssignment.starts_at <= now,
                (EmployeeAssignment.ends_at.is_(None))
                | (EmployeeAssignment.ends_at > now),
                AssignmentVenue.company_id == company_id,
                AssignmentVenue.venue_id.in_(venue_ids),
            )
            .limit(1)
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None
