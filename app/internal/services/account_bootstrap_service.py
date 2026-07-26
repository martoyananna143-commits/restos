"""Read-only Account bootstrap projection for browser clients."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.access_profile import AccessProfile
from app.infra.database.models.account import Account
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position


class AccountBootstrapUnavailable(Exception):
    """The authenticated account is no longer eligible."""


@dataclass(frozen=True)
class BootstrapCompany:
    company_id: UUID
    company_name: str
    employee_profile_id: UUID | None
    relationship: str


@dataclass(frozen=True)
class AccountBootstrap:
    account_id: UUID
    account_status: str
    security_version: int
    companies: tuple[BootstrapCompany, ...]


class AccountBootstrapService:
    """Build a deterministic bootstrap response using SELECT statements only."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, account_id: UUID, now: datetime) -> AccountBootstrap:
        if not isinstance(account_id, UUID):
            raise ValueError("account_id must be a UUID")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        account = (
            await self._session.execute(
                select(Account).where(
                    Account.id == account_id,
                    Account.status == "active",
                    Account.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if account is None:
            raise AccountBootstrapUnavailable("account is unavailable")

        owners = (
            await self._session.execute(
                select(Company.id, Company.name).where(
                    Company.owner_account_id == account_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
            )
        ).all()
        employees = (
            await self._session.execute(
                select(Company.id, Company.name, EmployeeProfile.id)
                .join(EmployeeProfile, EmployeeProfile.company_id == Company.id)
                .join(
                    EmployeeAssignment,
                    and_(
                        EmployeeAssignment.company_id == Company.id,
                        EmployeeAssignment.employee_profile_id == EmployeeProfile.id,
                    ),
                )
                .join(
                    Position,
                    and_(
                        Position.id == EmployeeAssignment.position_id,
                        Position.company_id == Company.id,
                    ),
                )
                .join(
                    AccessProfile,
                    and_(
                        AccessProfile.id == EmployeeAssignment.access_profile_id,
                        AccessProfile.company_id == Company.id,
                    ),
                )
                .where(
                    EmployeeProfile.account_id == account_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeAssignment.status == "active",
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.starts_at <= now,
                    or_(
                        EmployeeAssignment.ends_at.is_(None),
                        EmployeeAssignment.ends_at > now,
                    ),
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
                .distinct()
            )
        ).all()

        companies = {
            company_id: BootstrapCompany(company_id, name, None, "owner")
            for company_id, name in owners
        }
        for company_id, name, profile_id in employees:
            companies.setdefault(
                company_id,
                BootstrapCompany(company_id, name, profile_id, "employee"),
            )
        ordered = tuple(
            sorted(
                companies.values(),
                key=lambda item: (
                    " ".join(item.company_name.split()).casefold(),
                    str(item.company_id),
                ),
            )
        )
        return AccountBootstrap(
            account_id=account.id,
            account_status=account.status,
            security_version=account.security_version,
            companies=ordered,
        )
