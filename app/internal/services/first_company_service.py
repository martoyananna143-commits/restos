"""Atomic first Company/Owner aggregate creation for standalone Accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue


OWNER_PERMISSION_CODES = (
    "assessment.assignment.manage",
    "assessment.assignment.read",
    "assessment.template.manage",
    "assessment.template.read",
    "audit.view",
    "company.manage",
    "employee.invite",
    "employee.manage",
    "employee.view",
    "venue.view",
)
_CODE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class FirstCompanyError(Exception):
    """Base error for safe first-company failures."""


class InvalidFirstCompanyRequest(FirstCompanyError):
    """The request cannot form a valid aggregate."""


class FirstCompanyUnavailable(FirstCompanyError):
    """The Account or an existing aggregate is unavailable."""


@dataclass(frozen=True)
class CreateFirstCompany:
    account_id: UUID
    expected_security_version: int
    company_name: str
    venue_name: str | None
    timezone: str
    locale: str
    now: datetime


@dataclass(frozen=True)
class FirstCompanyResult:
    created: bool
    company_id: UUID
    company_name: str
    company_code: str
    employee_profile_id: UUID
    position_id: UUID
    access_profile_id: UUID
    employee_assignment_id: UUID
    venue_id: UUID | None


CodeFactory = Callable[[str, int], str]


class FirstCompanyService:
    """Create the first owner aggregate without owning commit or rollback."""

    def __init__(
        self,
        session: AsyncSession,
        code_factory: CodeFactory | None = None,
    ):
        self._session = session
        self._code_factory = code_factory or self._default_code

    async def create(self, request: CreateFirstCompany) -> FirstCompanyResult:
        company_name = self._text(request.company_name, "company_name", 255)
        venue_name = (
            self._text(request.venue_name, "venue_name", 255)
            if request.venue_name is not None and request.venue_name.strip()
            else None
        )
        timezone = self._text(request.timezone, "timezone", 100)
        locale = self._text(request.locale, "locale", 35)
        if request.now.tzinfo is None or request.now.utcoffset() is None:
            raise InvalidFirstCompanyRequest("now must be timezone-aware")
        if request.expected_security_version < 1:
            raise InvalidFirstCompanyRequest("invalid security version")

        account = (
            await self._session.execute(
                select(Account)
                .where(
                    Account.id == request.account_id,
                    Account.status == "active",
                    Account.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if account is None or account.security_version != request.expected_security_version:
            raise FirstCompanyUnavailable("account is unavailable")

        existing = (
            await self._session.execute(
                select(Company)
                .where(
                    Company.owner_account_id == request.account_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
                .order_by(Company.created_at, Company.id)
            )
        ).scalars().first()
        if existing is not None:
            return await self._existing_result(existing)

        company_id = uuid4()
        company = Company(
            id=company_id,
            owner_account_id=account.id,
            name=company_name,
            code=await self._available_company_code(company_name),
            legal_name=None,
            tax_id=None,
            timezone=timezone,
            locale=locale,
            status="active",
            meta={},
        )
        access_profile = AccessProfile(
            id=uuid4(),
            company_id=company_id,
            name="Владелец",
            code="owner",
            description="Полный доступ владельца организации",
            maximum_scope="company",
            is_system=True,
            is_active=True,
            version=1,
        )
        position = Position(
            id=uuid4(),
            company_id=company_id,
            name="Владелец",
            code="owner",
            description=None,
            default_access_profile_id=access_profile.id,
            default_scope_type="company",
            is_active=True,
            sort_order=0,
        )
        employee_profile = EmployeeProfile(
            id=uuid4(),
            company_id=company_id,
            account_id=account.id,
            full_name=account.display_name,
            email=None,
            phone=None,
            employment_status="active",
            hired_at=request.now,
            terminated_at=None,
            meta={},
        )
        assignment = EmployeeAssignment(
            id=uuid4(),
            company_id=company_id,
            employee_profile_id=employee_profile.id,
            position_id=position.id,
            access_profile_id=access_profile.id,
            scope_type="company",
            is_primary=True,
            status="active",
            starts_at=request.now,
            ends_at=None,
            revoked_at=None,
            revoked_by_account_id=None,
            revoke_reason=None,
            legacy_employee_id=None,
        )
        venue = (
            Venue(
                id=uuid4(),
                company_id=company_id,
                legacy_organization_id=None,
                name=venue_name,
                code="first-venue",
                concept=None,
                address=None,
                phone=None,
                timezone=None,
                status="active",
                meta={},
            )
            if venue_name is not None
            else None
        )
        # The models intentionally expose no ORM relationships. Flush each FK
        # layer explicitly while retaining one caller-owned transaction.
        self._session.add(company)
        await self._session.flush()
        self._session.add(access_profile)
        await self._session.flush()
        self._session.add_all(
            [position, employee_profile] + ([venue] if venue is not None else [])
        )
        await self._session.flush()
        self._session.add(assignment)
        await self._session.flush()
        self._session.add_all(
            [
                AccessProfilePermission(
                    access_profile_id=access_profile.id,
                    permission_code=code,
                )
                for code in OWNER_PERMISSION_CODES
            ]
        )
        await self._session.flush()
        return FirstCompanyResult(
            created=True,
            company_id=company.id,
            company_name=company.name,
            company_code=company.code,
            employee_profile_id=employee_profile.id,
            position_id=position.id,
            access_profile_id=access_profile.id,
            employee_assignment_id=assignment.id,
            venue_id=venue.id if venue is not None else None,
        )

    async def _existing_result(self, company: Company) -> FirstCompanyResult:
        row = (
            await self._session.execute(
                select(EmployeeProfile, EmployeeAssignment, Position, AccessProfile)
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
                .join(
                    AccessProfile,
                    (AccessProfile.id == EmployeeAssignment.access_profile_id)
                    & (AccessProfile.company_id == EmployeeAssignment.company_id),
                )
                .where(
                    EmployeeProfile.company_id == company.id,
                    EmployeeProfile.account_id == company.owner_account_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeAssignment.status == "active",
                    EmployeeAssignment.is_primary.is_(True),
                    EmployeeAssignment.deleted_at.is_(None),
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                )
            )
        ).first()
        if row is None:
            raise FirstCompanyUnavailable("owner aggregate is unavailable")
        profile, assignment, position, access_profile = row
        venue_id = (
            await self._session.execute(
                select(Venue.id)
                .where(
                    Venue.company_id == company.id,
                    Venue.status == "active",
                    Venue.deleted_at.is_(None),
                )
                .order_by(Venue.created_at, Venue.id)
            )
        ).scalars().first()
        return FirstCompanyResult(
            created=False,
            company_id=company.id,
            company_name=company.name,
            company_code=company.code,
            employee_profile_id=profile.id,
            position_id=position.id,
            access_profile_id=access_profile.id,
            employee_assignment_id=assignment.id,
            venue_id=venue_id,
        )

    async def _available_company_code(self, company_name: str) -> str:
        for attempt in range(8):
            candidate = self._code_factory(company_name, attempt).strip().lower()
            if len(candidate) > 100 or _CODE_RE.fullmatch(candidate) is None:
                continue
            exists = (
                await self._session.execute(
                    select(Company.id).where(
                        Company.code == candidate,
                        Company.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                return candidate
        raise FirstCompanyUnavailable("company code is unavailable")

    @staticmethod
    def _default_code(_name: str, _attempt: int) -> str:
        return f"company-{uuid4().hex[:16]}"

    @staticmethod
    def _text(value: str, field: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise InvalidFirstCompanyRequest(f"{field} must be text")
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > maximum:
            raise InvalidFirstCompanyRequest(f"invalid {field}")
        return normalized
