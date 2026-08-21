"""Account-scoped orchestration for one safe workforce invitation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.company import Company
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import Invitation
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.phone_verification_service import PhoneVerificationService
from app.internal.services.workforce_invitation_service import (
    CreateWorkforceInvitation,
    WorkforceInvitationForbidden,
    WorkforceInvitationService,
)


_ID_NAMESPACE = UUID("5ef15d3f-05fe-42a6-baa2-3746b670b591")
_CODE_ATTEMPTS = 10
_DEFAULT_TTL = timedelta(hours=24)


class AccountWorkforceOnboardingError(Exception):
    """Base controlled error."""


class AccountWorkforceOnboardingForbidden(AccountWorkforceOnboardingError):
    """Actor cannot invite within the requested company."""


class AccountWorkforceOnboardingInvalid(AccountWorkforceOnboardingError):
    """Input or referenced company data is invalid."""


class AccountWorkforceOnboardingConflict(AccountWorkforceOnboardingError):
    """Idempotency scope is unavailable for a different operation."""


@dataclass(frozen=True)
class CreateAccountWorkforceInvitation:
    actor_account_id: UUID
    company_id: UUID
    request_id: UUID
    employee_name: str
    phone: str
    venue_id: UUID | None
    now: datetime


@dataclass(frozen=True)
class AccountWorkforceInvitationResult:
    created: bool
    invitation_id: UUID
    employee_profile_id: UUID
    code: str
    expires_at: datetime


class AccountWorkforceOnboardingService:
    """Create an invited profile and invitation in the caller transaction."""

    def __init__(
        self,
        session: AsyncSession,
        invitation_pepper: bytes,
        phone_pepper: bytes,
    ):
        if not isinstance(invitation_pepper, bytes) or len(invitation_pepper) < 32:
            raise ValueError("invitation_pepper must contain at least 32 bytes")
        if not isinstance(phone_pepper, bytes) or len(phone_pepper) < 32:
            raise ValueError("phone_pepper must contain at least 32 bytes")
        self._session = session
        self._pepper = invitation_pepper
        self._phone_pepper = phone_pepper
        self._access = AccessDecisionService(session)

    async def list_venues(
        self, actor_account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, object]]:
        membership = (
            await self._session.execute(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.account_id == actor_account_id,
                    EmployeeProfile.company_id == company_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        company_access = await self._access.can_in_company(
            actor_account_id, company_id, "venue.view", now
        )
        venue_ids = await self._access.list_accessible_venue_ids(
            actor_account_id, company_id, "venue.view", now
        )
        if membership is None and not company_access:
            raise AccountWorkforceOnboardingForbidden("invitation is forbidden")
        if not company_access and not venue_ids:
            return []
        rows = (
            await self._session.execute(
                select(Venue)
                .where(
                    Venue.company_id == company_id,
                    *([] if company_access else [Venue.id.in_(venue_ids)]),
                    Venue.status == "active",
                    Venue.deleted_at.is_(None),
                )
                .order_by(Venue.name, Venue.id)
            )
        ).scalars()
        return [{"venue_id": venue.id, "name": venue.name} for venue in rows]

    async def create_invitation(
        self, command: CreateAccountWorkforceInvitation
    ) -> AccountWorkforceInvitationResult:
        name = self._text(command.employee_name)
        try:
            phone = PhoneVerificationService.normalize_e164(command.phone)
        except Exception as error:
            raise AccountWorkforceOnboardingInvalid("phone is invalid") from error
        if command.now.tzinfo is None or command.now.utcoffset() is None:
            raise AccountWorkforceOnboardingInvalid("now must be timezone-aware")
        for value in (
            command.actor_account_id,
            command.company_id,
            command.request_id,
        ):
            if not isinstance(value, UUID):
                raise AccountWorkforceOnboardingInvalid("identifiers must be UUIDs")
        if command.venue_id is not None and not isinstance(command.venue_id, UUID):
            raise AccountWorkforceOnboardingInvalid("venue_id must be a UUID")

        company = (
            await self._session.execute(
                select(Company)
                .where(
                    Company.id == command.company_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if company is None:
            raise AccountWorkforceOnboardingInvalid("company is unavailable")
        if not await self._access.can_in_company(
            command.actor_account_id,
            command.company_id,
            "employee.invite",
            command.now,
        ):
            raise AccountWorkforceOnboardingForbidden("invitation is forbidden")

        employee_profile_id = uuid5(
            _ID_NAMESPACE,
            f"employee-profile-v1:{command.company_id}:{command.request_id}",
        )
        existing_profile = await self._session.get(EmployeeProfile, employee_profile_id)
        if existing_profile is not None:
            return await self._existing_result(
                command, existing_profile, employee_profile_id, name, phone
            )

        incompatible_profile = (
            await self._session.execute(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.id != employee_profile_id,
                    EmployeeProfile.company_id == command.company_id,
                    EmployeeProfile.phone == phone,
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeProfile.employment_status != "terminated",
                )
            )
        ).scalar_one_or_none()
        if incompatible_profile is not None:
            raise AccountWorkforceOnboardingConflict(
                "workforce invitation is unavailable"
            )

        access_profile, position = await self._employee_defaults(command.company_id)
        profile = EmployeeProfile(
            id=employee_profile_id,
            company_id=command.company_id,
            account_id=None,
            full_name=name,
            email=None,
            phone=phone,
            employment_status="invited",
            hired_at=None,
            terminated_at=None,
            meta={"source": "account_invitation_v1"},
        )
        try:
            async with self._session.begin_nested():
                self._session.add(profile)
                await self._session.flush()
        except IntegrityError as error:
            if (
                _postgres_constraint_name(error)
                == "uq_employee_profiles_active_company_phone"
            ):
                raise AccountWorkforceOnboardingConflict(
                    "workforce invitation is unavailable"
                ) from error
            raise

        codes = self._candidate_codes(command)
        index = 0

        def next_code() -> str:
            nonlocal index
            if index >= len(codes):
                return codes[-1]
            value = codes[index]
            index += 1
            return value

        workforce = WorkforceInvitationService(
            self._session,
            self._access,
            self._pepper,
            code_generator=next_code,
        )
        try:
            created = await workforce.create(
                CreateWorkforceInvitation(
                    actor_account_id=command.actor_account_id,
                    company_id=command.company_id,
                    employee_profile_id=employee_profile_id,
                    position_id=position.id,
                    access_profile_id=access_profile.id,
                    scope_type=(
                        "working_venues" if command.venue_id is not None else "self"
                    ),
                    working_venue_ids=(
                        (command.venue_id,) if command.venue_id is not None else ()
                    ),
                    scope_venue_ids=(),
                    now=command.now,
                    ttl=_DEFAULT_TTL,
                )
            )
        except WorkforceInvitationForbidden as error:
            raise AccountWorkforceOnboardingForbidden(
                "invitation is forbidden"
            ) from error
        return AccountWorkforceInvitationResult(
            created=True,
            invitation_id=created.invitation_id,
            employee_profile_id=employee_profile_id,
            code=created.code,
            expires_at=created.expires_at,
        )

    async def _existing_result(
        self,
        command: CreateAccountWorkforceInvitation,
        profile: EmployeeProfile,
        profile_id: UUID,
        expected_name: str,
        expected_phone: str,
    ) -> AccountWorkforceInvitationResult:
        if (
            profile.company_id != command.company_id
            or profile.full_name != expected_name
            or profile.phone != expected_phone
            or profile.account_id is not None
            or profile.employment_status != "invited"
            or profile.deleted_at is not None
            or profile.meta.get("source") != "account_invitation_v1"
        ):
            raise AccountWorkforceOnboardingConflict("request_id is unavailable")
        invitation = (
            await self._session.execute(
                select(Invitation).where(
                    Invitation.company_id == command.company_id,
                    Invitation.employee_profile_id == profile_id,
                    Invitation.created_by_account_id == command.actor_account_id,
                    Invitation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if (
            invitation is None
            or invitation.status != "pending"
            or invitation.expires_at <= command.now
        ):
            raise AccountWorkforceOnboardingConflict("request_id is unavailable")
        code = self._matching_code(command, invitation.code_digest)
        if code is None:
            raise AccountWorkforceOnboardingConflict("request_id is unavailable")
        return AccountWorkforceInvitationResult(
            created=False,
            invitation_id=invitation.id,
            employee_profile_id=profile_id,
            code=code,
            expires_at=invitation.expires_at,
        )

    async def _employee_defaults(
        self, company_id: UUID
    ) -> tuple[AccessProfile, Position]:
        expected_access_id = uuid5(
            _ID_NAMESPACE, f"employee-access-v1:{company_id}"
        )
        access_profile = (
            await self._session.execute(
                select(AccessProfile).where(
                    AccessProfile.company_id == company_id,
                    AccessProfile.code == "employee",
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if access_profile is None:
            access_profile = AccessProfile(
                id=expected_access_id,
                company_id=company_id,
                name="Сотрудник",
                code="employee",
                description="Базовый доступ сотрудника",
                maximum_scope="working_venues",
                is_system=True,
                is_active=True,
                version=1,
            )
            self._session.add(access_profile)
            await self._session.flush()
        elif (
            not access_profile.is_system
            or access_profile.maximum_scope != "working_venues"
        ):
            raise AccountWorkforceOnboardingConflict(
                "employee access profile is incompatible"
            )
        permissions = set(
            (
                await self._session.execute(
                    select(AccessProfilePermission.permission_code).where(
                        AccessProfilePermission.access_profile_id == access_profile.id
                    )
                )
            ).scalars()
        )
        if permissions - {"venue.view"}:
            raise AccountWorkforceOnboardingConflict(
                "employee access profile is incompatible"
            )
        if "venue.view" not in permissions:
            self._session.add(
                AccessProfilePermission(
                    access_profile_id=access_profile.id,
                    permission_code="venue.view",
                )
            )
            await self._session.flush()

        expected_position_id = uuid5(
            _ID_NAMESPACE, f"employee-position-v1:{company_id}"
        )
        position = (
            await self._session.execute(
                select(Position).where(
                    Position.company_id == company_id,
                    Position.code == "employee",
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if position is None:
            position = Position(
                id=expected_position_id,
                company_id=company_id,
                name="Сотрудник",
                code="employee",
                description=None,
                default_access_profile_id=access_profile.id,
                is_active=True,
                sort_order=100,
            )
            self._session.add(position)
            await self._session.flush()
        elif position.default_access_profile_id != access_profile.id:
            raise AccountWorkforceOnboardingConflict(
                "employee position is incompatible"
            )
        return access_profile, position

    def _candidate_codes(
        self, command: CreateAccountWorkforceInvitation
    ) -> tuple[str, ...]:
        prefix = (
            f"account-workforce-code-v1:{command.company_id}:"
            f"{command.request_id}:"
        )
        return tuple(
            f"{int.from_bytes(hmac.new(self._pepper, f'{prefix}{index}'.encode('ascii'), hashlib.sha256).digest()[:8], 'big') % 1_000_000:06d}"
            for index in range(_CODE_ATTEMPTS)
        )

    def _matching_code(
        self, command: CreateAccountWorkforceInvitation, digest: bytes
    ) -> str | None:
        for code in self._candidate_codes(command):
            candidate = hmac.new(
                self._pepper, code.encode("ascii"), hashlib.sha256
            ).digest()
            if hmac.compare_digest(candidate, digest):
                return code
        return None

    @staticmethod
    def _text(value: str) -> str:
        if not isinstance(value, str):
            raise AccountWorkforceOnboardingInvalid("employee_name must be text")
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > 255:
            raise AccountWorkforceOnboardingInvalid("invalid employee_name")
        return normalized


def _postgres_constraint_name(error: IntegrityError) -> str | None:
    current = error.orig
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        diag = getattr(current, "diag", None)
        name = getattr(diag, "constraint_name", None) or getattr(
            current, "constraint_name", None
        )
        if name:
            return name
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )
    return None
