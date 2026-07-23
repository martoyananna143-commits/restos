"""Secure creation of additive workforce invitations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable, Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.access_profile import AccessProfile
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


_SCOPE_RANK = {
    "self": 0,
    "working_venues": 1,
    "explicit_venues": 2,
    "company": 3,
}
_MIN_TTL = timedelta(minutes=5)
_MAX_TTL = timedelta(days=7)
_MAX_CODE_ATTEMPTS = 10
_SIX_ASCII_DIGITS = re.compile(r"^[0-9]{6}$")


class WorkforceInvitationError(Exception):
    """Base controlled workforce invitation error."""


class InvalidWorkforceInvitation(WorkforceInvitationError):
    """Input or referenced business objects are invalid."""


class WorkforceInvitationForbidden(WorkforceInvitationError):
    """Actor is not authorized for the complete invitation scope."""


class PendingWorkforceInvitationExists(WorkforceInvitationError):
    """Employee profile already has an active pending invitation."""


class InvitationCodeCollisionExhausted(WorkforceInvitationError):
    """No unique six-digit code was found within the attempt limit."""


@dataclass(frozen=True)
class CreateWorkforceInvitation:
    actor_account_id: UUID
    company_id: UUID
    employee_profile_id: UUID
    position_id: UUID
    access_profile_id: UUID
    scope_type: str
    working_venue_ids: Iterable[UUID]
    scope_venue_ids: Iterable[UUID]
    now: datetime
    expires_at: datetime | None = None
    ttl: timedelta | None = None


@dataclass(frozen=True)
class CreatedWorkforceInvitation:
    invitation_id: UUID
    code: str
    expires_at: datetime


class WorkforceInvitationService:
    """Create pending invitations without owning the caller's transaction."""

    def __init__(
        self,
        session: AsyncSession,
        access_decisions: AccessDecisionService,
        pepper: bytes,
        code_generator: Callable[[], str] | None = None,
    ):
        if not isinstance(pepper, bytes) or len(pepper) < 32:
            raise ValueError("pepper must contain at least 32 bytes")
        self._session = session
        self._access = access_decisions
        self._pepper = pepper
        self._code_generator = code_generator or self._generate_code

    async def create(
        self, request: CreateWorkforceInvitation
    ) -> CreatedWorkforceInvitation:
        """Create one pending invitation and return its plaintext code once."""
        working_ids, scope_ids, expires_at = self._validate_input(request)
        maximum_scope = await self._validate_business_objects(
            request, working_ids | scope_ids
        )
        if _SCOPE_RANK[request.scope_type] > _SCOPE_RANK[maximum_scope]:
            raise InvalidWorkforceInvitation(
                "invitation scope exceeds access profile maximum_scope"
            )
        self._validate_scope_lists(request.scope_type, working_ids, scope_ids)
        await self._authorize(request, working_ids | scope_ids)
        await self._expire_or_reject_pending(
            request.employee_profile_id, request.now
        )

        for _ in range(_MAX_CODE_ATTEMPTS):
            invitation_id = uuid4()
            code = self._code_generator()
            if not isinstance(code, str) or not _SIX_ASCII_DIGITS.fullmatch(code):
                raise InvalidWorkforceInvitation(
                    "code generator must return exactly six digits"
                )
            digest = hmac.new(
                self._pepper, code.encode("ascii"), hashlib.sha256
            ).digest()
            invitation = Invitation(
                id=invitation_id,
                company_id=request.company_id,
                employee_profile_id=request.employee_profile_id,
                position_id=request.position_id,
                access_profile_id=request.access_profile_id,
                scope_type=request.scope_type,
                code_digest=digest,
                status="pending",
                created_by_account_id=request.actor_account_id,
                expires_at=expires_at,
                created_at=request.now,
                updated_at=request.now,
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(invitation)
                    await self._session.flush()
            except IntegrityError as error:
                constraint = _postgres_constraint_name(error)
                if constraint == "uq_invitations_active_code_digest":
                    continue
                if constraint == "uq_invitations_pending_employee_profile":
                    raise PendingWorkforceInvitationExists(
                        "pending invitation already exists for employee profile"
                    ) from error
                raise

            self._session.add_all(
                [
                    InvitationVenue(
                        invitation_id=invitation_id,
                        venue_id=venue_id,
                        company_id=request.company_id,
                    )
                    for venue_id in working_ids
                ]
                + [
                    InvitationScopeVenue(
                        invitation_id=invitation_id,
                        venue_id=venue_id,
                        company_id=request.company_id,
                    )
                    for venue_id in scope_ids
                ]
            )
            await self._session.flush()
            return CreatedWorkforceInvitation(invitation_id, code, expires_at)
        raise InvitationCodeCollisionExhausted(
            "six-digit invitation code attempts exhausted"
        )

    @staticmethod
    def _generate_code() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _require_aware(name: str, value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise InvalidWorkforceInvitation(f"{name} must be timezone-aware")

    def _validate_input(
        self, request: CreateWorkforceInvitation
    ) -> tuple[set[UUID], set[UUID], datetime]:
        for name in (
            "actor_account_id",
            "company_id",
            "employee_profile_id",
            "position_id",
            "access_profile_id",
        ):
            if not isinstance(getattr(request, name), UUID):
                raise InvalidWorkforceInvitation(f"{name} must be a UUID")
        if request.scope_type not in _SCOPE_RANK:
            raise InvalidWorkforceInvitation("invalid scope_type")
        self._require_aware("now", request.now)
        if (request.expires_at is None) == (request.ttl is None):
            raise InvalidWorkforceInvitation(
                "provide exactly one of expires_at or ttl"
            )
        expires_at = request.expires_at or request.now + request.ttl  # type: ignore[operator]
        self._require_aware("expires_at", expires_at)
        ttl = expires_at - request.now
        if ttl < _MIN_TTL or ttl > _MAX_TTL:
            raise InvalidWorkforceInvitation(
                "invitation lifetime must be from 5 minutes to 7 days"
            )
        working_ids = self._normalize_uuid_set(
            "working_venue_ids", request.working_venue_ids
        )
        scope_ids = self._normalize_uuid_set(
            "scope_venue_ids", request.scope_venue_ids
        )
        return working_ids, scope_ids, expires_at

    @staticmethod
    def _normalize_uuid_set(name: str, values: Iterable[UUID]) -> set[UUID]:
        result = set(values)
        if any(not isinstance(value, UUID) for value in result):
            raise InvalidWorkforceInvitation(f"{name} must contain UUID values")
        return result

    @staticmethod
    def _validate_scope_lists(
        scope_type: str, working_ids: set[UUID], scope_ids: set[UUID]
    ) -> None:
        if scope_type == "working_venues" and not working_ids:
            raise InvalidWorkforceInvitation(
                "working_venues scope requires working venues"
            )
        if scope_type == "explicit_venues" and not scope_ids:
            raise InvalidWorkforceInvitation(
                "explicit_venues scope requires scope venues"
            )
        if scope_type in {"self", "company"} and scope_ids:
            raise InvalidWorkforceInvitation(
                f"{scope_type} scope forbids scope venues"
            )

    async def _validate_business_objects(
        self,
        request: CreateWorkforceInvitation,
        venue_ids: set[UUID],
    ) -> str:
        company = (
            await self._session.execute(
                select(Company.id).where(
                    Company.id == request.company_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if company is None:
            raise InvalidWorkforceInvitation("company is unavailable")

        profile = (
            await self._session.execute(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.id == request.employee_profile_id,
                    EmployeeProfile.company_id == request.company_id,
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeProfile.account_id.is_(None),
                    EmployeeProfile.employment_status == "invited",
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            raise InvalidWorkforceInvitation(
                "employee profile is not invitible"
            )

        position = (
            await self._session.execute(
                select(Position.id).where(
                    Position.id == request.position_id,
                    Position.company_id == request.company_id,
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if position is None:
            raise InvalidWorkforceInvitation("position is unavailable")

        maximum_scope = (
            await self._session.execute(
                select(AccessProfile.maximum_scope).where(
                    AccessProfile.id == request.access_profile_id,
                    AccessProfile.company_id == request.company_id,
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if maximum_scope is None:
            raise InvalidWorkforceInvitation("access profile is unavailable")

        if venue_ids:
            found_ids = set(
                (
                    await self._session.execute(
                        select(Venue.id).where(
                            Venue.id.in_(venue_ids),
                            Venue.company_id == request.company_id,
                            Venue.deleted_at.is_(None),
                            Venue.status != "closed",
                        )
                    )
                ).scalars()
            )
            if found_ids != venue_ids:
                raise InvalidWorkforceInvitation(
                    "one or more venues are unavailable"
                )
        return maximum_scope

    async def _authorize(
        self,
        request: CreateWorkforceInvitation,
        venue_ids: set[UUID],
    ) -> None:
        if await self._access.can_in_company(
            request.actor_account_id,
            request.company_id,
            "employee.invite",
            request.now,
        ):
            return
        if request.scope_type == "company" or not venue_ids:
            raise WorkforceInvitationForbidden(
                "company-wide employee.invite permission is required"
            )
        for venue_id in venue_ids:
            if not await self._access.can_for_venue(
                request.actor_account_id,
                request.company_id,
                "employee.invite",
                venue_id,
                request.now,
            ):
                raise WorkforceInvitationForbidden(
                    "actor cannot invite for every selected venue"
                )

    async def _expire_or_reject_pending(
        self, employee_profile_id: UUID, now: datetime
    ) -> None:
        statement = select(Invitation).where(
            Invitation.employee_profile_id == employee_profile_id,
            Invitation.status == "pending",
            Invitation.deleted_at.is_(None),
        ).with_for_update()
        pending = (await self._session.execute(statement)).scalar_one_or_none()
        if pending is None:
            return
        if pending.expires_at <= now:
            pending.status = "expired"
            pending.updated_at = now
            await self._session.flush()
            return
        raise PendingWorkforceInvitationExists(
            "pending invitation already exists for employee profile"
        )


def _postgres_constraint_name(error: IntegrityError) -> str | None:
    """Read a PostgreSQL constraint name across DBAPI adapter wrappers."""
    current = error.orig
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        diag = getattr(current, "diag", None)
        name = getattr(diag, "constraint_name", None)
        if name:
            return name
        name = getattr(current, "constraint_name", None)
        if name:
            return name
        current = getattr(current, "__cause__", None) or getattr(
            current, "__context__", None
        )
    return None
