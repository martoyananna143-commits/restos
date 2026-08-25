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
from app.infra.database.models.invitation_v1 import (
    Invitation,
    InvitationScopeVenue,
    InvitationVenue,
)
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
    position_id: UUID
    venue_id: UUID | None
    now: datetime


@dataclass(frozen=True)
class AccountWorkforceInvitationResult:
    created: bool
    invitation_id: UUID
    employee_profile_id: UUID
    code: str
    phone: str
    expires_at: datetime
    delivery_status: str
    delivery_attempt_count: int
    should_send: bool
    invitation_status: str


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

    async def list_invitation_positions(
        self, actor_account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, object]]:
        company_access = await self._access.can_in_company(
            actor_account_id, company_id, "employee.invite", now
        )
        venue_ids = await self._access.list_accessible_venue_ids(
            actor_account_id, company_id, "employee.invite", now
        )
        if not company_access and not venue_ids:
            raise AccountWorkforceOnboardingForbidden("invitation is forbidden")
        statement = (
            select(Position, AccessProfile)
            .join(
                AccessProfile,
                (AccessProfile.id == Position.default_access_profile_id)
                & (AccessProfile.company_id == Position.company_id),
            )
            .where(
                Position.company_id == company_id,
                Position.is_active.is_(True),
                Position.deleted_at.is_(None),
                AccessProfile.is_active.is_(True),
                AccessProfile.deleted_at.is_(None),
                AccessProfile.code != "owner",
            )
            .order_by(Position.sort_order, Position.name, Position.id)
        )
        if not company_access:
            statement = statement.where(AccessProfile.maximum_scope != "company")
        rows = (await self._session.execute(statement)).all()
        return [
            {
                "position_id": position.id,
                "position_name": position.name,
                "access_profile_name": access_profile.name,
                "access_scope": position.default_scope_type
                or access_profile.maximum_scope,
            }
            for position, access_profile in rows
        ]

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
            command.position_id,
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

        access_profile, position, scope_type, working_ids, scope_ids = (
            await self._assignment_contract(command)
        )

        employee_profile_id = uuid5(
            _ID_NAMESPACE,
            f"employee-profile-v1:{command.company_id}:{command.request_id}",
        )
        existing_profile = await self._session.get(EmployeeProfile, employee_profile_id)
        if existing_profile is not None:
            return await self._existing_result(
                command,
                existing_profile,
                employee_profile_id,
                name,
                phone,
                access_profile,
                position,
                scope_type,
                working_ids,
                scope_ids,
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
                    scope_type=scope_type,
                    working_venue_ids=working_ids,
                    scope_venue_ids=scope_ids,
                    now=command.now,
                    ttl=_DEFAULT_TTL,
                )
            )
        except WorkforceInvitationForbidden as error:
            raise AccountWorkforceOnboardingForbidden(
                "invitation is forbidden"
            ) from error
        invitation = await self._session.get(Invitation, created.invitation_id)
        if invitation is None:
            raise AccountWorkforceOnboardingConflict("invitation is unavailable")
        invitation.delivery_status = "delivery_pending"
        invitation.delivery_attempt_count = 1
        invitation.delivery_attempted_at = command.now
        invitation.delivery_sent_at = None
        await self._session.flush()
        return AccountWorkforceInvitationResult(
            created=True,
            invitation_id=created.invitation_id,
            employee_profile_id=employee_profile_id,
            code=created.code,
            phone=phone,
            expires_at=created.expires_at,
            delivery_status="delivery_pending",
            delivery_attempt_count=1,
            should_send=True,
            invitation_status="pending",
        )

    async def _existing_result(
        self,
        command: CreateAccountWorkforceInvitation,
        profile: EmployeeProfile,
        profile_id: UUID,
        expected_name: str,
        expected_phone: str,
        access_profile: AccessProfile,
        position: Position,
        scope_type: str,
        working_ids: tuple[UUID, ...],
        scope_ids: tuple[UUID, ...],
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
                ).with_for_update()
            )
        ).scalar_one_or_none()
        if (
            invitation is None
            or invitation.status != "pending"
            or invitation.expires_at <= command.now
        ):
            raise AccountWorkforceOnboardingConflict("request_id is unavailable")
        persisted_working_ids = set(
            (
                await self._session.execute(
                    select(InvitationVenue.venue_id).where(
                        InvitationVenue.invitation_id == invitation.id
                    )
                )
            ).scalars()
        )
        persisted_scope_ids = set(
            (
                await self._session.execute(
                    select(InvitationScopeVenue.venue_id).where(
                        InvitationScopeVenue.invitation_id == invitation.id
                    )
                )
            ).scalars()
        )
        if (
            invitation.position_id != position.id
            or invitation.access_profile_id != access_profile.id
            or invitation.scope_type != scope_type
            or persisted_working_ids != set(working_ids)
            or persisted_scope_ids != set(scope_ids)
        ):
            raise AccountWorkforceOnboardingConflict("request_id is unavailable")
        code = self._matching_code(command, invitation.code_digest)
        if code is None:
            raise AccountWorkforceOnboardingConflict("request_id is unavailable")
        should_send = invitation.delivery_status == "failed"
        if should_send:
            invitation.delivery_status = "delivery_pending"
            invitation.delivery_attempt_count += 1
            invitation.delivery_attempted_at = command.now
            invitation.delivery_sent_at = None
            await self._session.flush()
        return AccountWorkforceInvitationResult(
            created=False,
            invitation_id=invitation.id,
            employee_profile_id=profile_id,
            code=code,
            phone=expected_phone,
            expires_at=invitation.expires_at,
            delivery_status=invitation.delivery_status,
            delivery_attempt_count=invitation.delivery_attempt_count,
            should_send=should_send,
            invitation_status=invitation.status,
        )

    async def record_delivery_outcome(
        self,
        invitation_id: UUID,
        outcome: str,
        now: datetime,
    ) -> str:
        """Complete one claimed attempt without reopening an ambiguous outcome."""

        if outcome not in {"sent", "unknown", "failed"}:
            raise AccountWorkforceOnboardingInvalid("invalid delivery outcome")
        if now.tzinfo is None or now.utcoffset() is None:
            raise AccountWorkforceOnboardingInvalid("now must be timezone-aware")
        invitation = (
            await self._session.execute(
                select(Invitation)
                .where(
                    Invitation.id == invitation_id,
                    Invitation.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise AccountWorkforceOnboardingConflict("invitation is unavailable")
        if invitation.delivery_status != "delivery_pending":
            return invitation.delivery_status
        invitation.delivery_status = outcome
        invitation.delivery_sent_at = now if outcome == "sent" else None
        await self._session.flush()
        return outcome

    async def _assignment_contract(
        self, command: CreateAccountWorkforceInvitation
    ) -> tuple[AccessProfile, Position, str, tuple[UUID, ...], tuple[UUID, ...]]:
        row = (
            await self._session.execute(
                select(Position, AccessProfile)
                .join(
                    AccessProfile,
                    (AccessProfile.id == Position.default_access_profile_id)
                    & (AccessProfile.company_id == Position.company_id),
                )
                .where(
                    Position.id == command.position_id,
                    Position.company_id == command.company_id,
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                    AccessProfile.code != "owner",
                )
            )
        ).one_or_none()
        if row is None:
            raise AccountWorkforceOnboardingInvalid("position is unavailable")
        position, access_profile = row
        scope_type = position.default_scope_type or access_profile.maximum_scope
        if scope_type not in {"self", "working_venues", "explicit_venues", "company"}:
            raise AccountWorkforceOnboardingInvalid("position scope is unavailable")
        if command.venue_id is None and scope_type in {"working_venues", "explicit_venues"}:
            raise AccountWorkforceOnboardingInvalid("position requires a venue")
        working_ids = (command.venue_id,) if command.venue_id is not None else ()
        scope_ids = (
            (command.venue_id,)
            if command.venue_id is not None and scope_type == "explicit_venues"
            else ()
        )
        return access_profile, position, scope_type, working_ids, scope_ids

    async def invitation_status(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        invitation_id: UUID,
        now: datetime,
    ) -> tuple[str, str]:
        if not await self._access.can_in_company(
            actor_account_id, company_id, "employee.invite", now
        ):
            raise AccountWorkforceOnboardingForbidden("invitation is forbidden")
        invitation = (
            await self._session.execute(
                select(Invitation).where(
                    Invitation.id == invitation_id,
                    Invitation.company_id == company_id,
                    Invitation.created_by_account_id == actor_account_id,
                    Invitation.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise AccountWorkforceOnboardingInvalid("invitation is unavailable")
        if invitation.status not in {"pending", "accepted"}:
            raise AccountWorkforceOnboardingInvalid("invitation is unavailable")
        return invitation.status, invitation.delivery_status

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
