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
from app.infra.database.models.account import Account, AccountIdentity
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
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


class InvalidOrUnavailableInvitation(WorkforceInvitationError):
    """Invitation code is invalid, unknown, expired, or no longer pending."""


class AccountUnavailableForInvitation(WorkforceInvitationError):
    """The accepting account is not active and available."""


class AccountAlreadyMemberOfCompany(WorkforceInvitationError):
    """The accepting account already has a profile in the company."""


class InvitationNoLongerApplicable(WorkforceInvitationError):
    """The invitation's referenced workforce data is no longer applicable."""


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


@dataclass(frozen=True)
class AcceptWorkforceInvitation:
    account_id: UUID
    code: str
    now: datetime


@dataclass(frozen=True)
class AcceptAuthenticatedWorkforceInvitation:
    account_id: UUID
    code: str
    now: datetime


@dataclass(frozen=True)
class AcceptedWorkforceInvitation:
    invitation_id: UUID
    company_id: UUID
    employee_profile_id: UUID
    employee_assignment_id: UUID
    position_id: UUID
    access_profile_id: UUID
    scope_type: str
    working_venue_ids: set[UUID]
    scope_venue_ids: set[UUID]


@dataclass(frozen=True)
class WorkforceInvitationAcceptanceProjection:
    company_name: str
    position_name: str
    venue_names: tuple[str, ...]


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

    async def accept(
        self, request: AcceptWorkforceInvitation
    ) -> AcceptedWorkforceInvitation:
        """Atomically accept one pending invitation inside a savepoint."""
        self._validate_accept_input(request)
        digest = hmac.new(
            self._pepper, request.code.encode("ascii"), hashlib.sha256
        ).digest()
        try:
            async with self._session.begin_nested():
                result = await self._accept_locked(request, digest)
                await self._session.flush()
                return result
        except IntegrityError as error:
            constraint = _postgres_constraint_name(error)
            if constraint == "uq_employee_profiles_active_company_account":
                raise AccountAlreadyMemberOfCompany(
                    "account already belongs to this company"
                ) from error
            raise

    async def accept_authenticated(
        self,
        request: AcceptAuthenticatedWorkforceInvitation,
        phone_pepper: bytes,
    ) -> AcceptedWorkforceInvitation:
        """Accept an invitation only when it matches the Account's verified phone."""
        self._validate_accept_input(
            AcceptWorkforceInvitation(request.account_id, request.code, request.now)
        )
        if not isinstance(phone_pepper, bytes) or len(phone_pepper) < 32:
            raise ValueError("phone_pepper must contain at least 32 bytes")
        digest = hmac.new(
            self._pepper, request.code.encode("ascii"), hashlib.sha256
        ).digest()
        try:
            async with self._session.begin_nested():
                invitation = (
                    await self._session.execute(
                        select(Invitation)
                        .where(
                            Invitation.code_digest == digest,
                            Invitation.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if invitation is None or not hmac.compare_digest(
                    invitation.code_digest, digest
                ):
                    raise InvalidOrUnavailableInvitation(
                        "invitation is unavailable"
                    )
                await self._require_authenticated_phone_match(
                    invitation, request.account_id, phone_pepper
                )
                if invitation.status == "accepted":
                    result = await self._accepted_result_for_replay(
                        invitation, request.account_id
                    )
                elif (
                    invitation.status == "pending"
                    and invitation.expires_at > request.now
                ):
                    result = await self._accept_locked(
                        AcceptWorkforceInvitation(
                            request.account_id, request.code, request.now
                        ),
                        digest,
                    )
                else:
                    raise InvalidOrUnavailableInvitation(
                        "invitation is unavailable"
                    )
                await self._session.flush()
                return result
        except IntegrityError as error:
            constraint = _postgres_constraint_name(error)
            if constraint == "uq_employee_profiles_active_company_account":
                raise AccountAlreadyMemberOfCompany(
                    "account already belongs to this company"
                ) from error
            raise

    async def acceptance_projection(
        self, accepted: AcceptedWorkforceInvitation
    ) -> WorkforceInvitationAcceptanceProjection:
        """Return the safe terminal projection after invitation acceptance."""

        company_name = (
            await self._session.execute(
                select(Company.name).where(
                    Company.id == accepted.company_id,
                    Company.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        position_name = (
            await self._session.execute(
                select(Position.name).where(
                    Position.id == accepted.position_id,
                    Position.company_id == accepted.company_id,
                    Position.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        venue_ids = accepted.working_venue_ids | accepted.scope_venue_ids
        venue_names: tuple[str, ...] = ()
        if venue_ids:
            venue_names = tuple(
                (
                    await self._session.execute(
                        select(Venue.name)
                        .where(
                            Venue.id.in_(venue_ids),
                            Venue.company_id == accepted.company_id,
                            Venue.deleted_at.is_(None),
                        )
                        .order_by(Venue.name, Venue.id)
                    )
                ).scalars()
            )
        if company_name is None or position_name is None:
            raise InvitationNoLongerApplicable("invitation projection is unavailable")
        return WorkforceInvitationAcceptanceProjection(
            company_name=company_name,
            position_name=position_name,
            venue_names=venue_names,
        )

    async def _require_authenticated_phone_match(
        self,
        invitation: Invitation,
        account_id: UUID,
        phone_pepper: bytes,
    ) -> None:
        account = (
            await self._session.execute(
                select(Account.id)
                .where(
                    Account.id == account_id,
                    Account.status == "active",
                    Account.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        profile = (
            await self._session.execute(
                select(EmployeeProfile)
                .where(EmployeeProfile.id == invitation.employee_profile_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        identity_digest = (
            await self._session.execute(
                select(AccountIdentity.subject_digest).where(
                    AccountIdentity.account_id == account_id,
                    AccountIdentity.identity_type == "phone",
                    AccountIdentity.provider == "e164",
                    AccountIdentity.status == "verified",
                    AccountIdentity.is_primary.is_(True),
                    AccountIdentity.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if (
            account is None
            or profile is None
            or profile.company_id != invitation.company_id
            or profile.deleted_at is not None
            or profile.phone is None
            or identity_digest is None
        ):
            raise InvalidOrUnavailableInvitation("invitation is unavailable")
        try:
            phone = PhoneVerificationService.normalize_e164(profile.phone)
        except Exception as error:
            raise InvalidOrUnavailableInvitation(
                "invitation is unavailable"
            ) from error
        expected_digest = hmac.new(
            phone_pepper, phone.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(identity_digest, expected_digest):
            raise InvalidOrUnavailableInvitation("invitation is unavailable")

    async def _accepted_result_for_replay(
        self, invitation: Invitation, account_id: UUID
    ) -> AcceptedWorkforceInvitation:
        profile = await self._session.get(
            EmployeeProfile, invitation.employee_profile_id
        )
        assignment = (
            await self._session.execute(
                select(EmployeeAssignment).where(
                    EmployeeAssignment.id == invitation.accepted_assignment_id,
                    EmployeeAssignment.company_id == invitation.company_id,
                    EmployeeAssignment.employee_profile_id
                    == invitation.employee_profile_id,
                )
            )
        ).scalar_one_or_none()
        if (
            invitation.accepted_by_account_id != account_id
            or invitation.accepted_assignment_id is None
            or profile is None
            or profile.account_id != account_id
            or profile.employment_status != "active"
            or profile.deleted_at is not None
            or assignment is None
        ):
            raise InvalidOrUnavailableInvitation("invitation is unavailable")
        working_ids, scope_ids = await self._locked_invitation_venues(invitation)
        return AcceptedWorkforceInvitation(
            invitation_id=invitation.id,
            company_id=invitation.company_id,
            employee_profile_id=invitation.employee_profile_id,
            employee_assignment_id=assignment.id,
            position_id=invitation.position_id,
            access_profile_id=invitation.access_profile_id,
            scope_type=invitation.scope_type,
            working_venue_ids=working_ids,
            scope_venue_ids=scope_ids,
        )

    def _validate_accept_input(self, request: AcceptWorkforceInvitation) -> None:
        if not isinstance(request.account_id, UUID):
            raise AccountUnavailableForInvitation("account_id must be a UUID")
        if not isinstance(request.code, str) or not _SIX_ASCII_DIGITS.fullmatch(
            request.code
        ):
            raise InvalidOrUnavailableInvitation("invitation is unavailable")
        try:
            self._require_aware("now", request.now)
        except InvalidWorkforceInvitation as error:
            raise InvalidOrUnavailableInvitation("invitation is unavailable") from error

    async def _accept_locked(
        self, request: AcceptWorkforceInvitation, digest: bytes
    ) -> AcceptedWorkforceInvitation:
        invitation = (
            await self._session.execute(
                select(Invitation)
                .where(
                    Invitation.code_digest == digest,
                    Invitation.status == "pending",
                    Invitation.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if invitation is None or not hmac.compare_digest(
            invitation.code_digest, digest
        ):
            raise InvalidOrUnavailableInvitation("invitation is unavailable")
        if (
            invitation.status != "pending"
            or invitation.deleted_at is not None
            or invitation.expires_at <= request.now
        ):
            raise InvalidOrUnavailableInvitation("invitation is unavailable")

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
        if account is None:
            raise AccountUnavailableForInvitation("account is unavailable")

        existing_profile = (
            await self._session.execute(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.company_id == invitation.company_id,
                    EmployeeProfile.account_id == request.account_id,
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_profile is not None:
            raise AccountAlreadyMemberOfCompany(
                "account already belongs to this company"
            )

        profile = (
            await self._session.execute(
                select(EmployeeProfile)
                .where(EmployeeProfile.id == invitation.employee_profile_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            profile is None
            or profile.company_id != invitation.company_id
            or profile.deleted_at is not None
            or profile.employment_status != "invited"
            or profile.account_id is not None
        ):
            raise InvitationNoLongerApplicable(
                "employee profile is no longer invitible"
            )

        maximum_scope = await self._validate_acceptance_objects(invitation)
        if _SCOPE_RANK[invitation.scope_type] > _SCOPE_RANK[maximum_scope]:
            raise InvitationNoLongerApplicable(
                "invitation scope exceeds access profile maximum_scope"
            )
        working_ids, scope_ids = await self._locked_invitation_venues(invitation)
        try:
            self._validate_scope_lists(invitation.scope_type, working_ids, scope_ids)
        except InvalidWorkforceInvitation as error:
            raise InvitationNoLongerApplicable(str(error)) from error

        profile.account_id = request.account_id
        profile.employment_status = "active"
        if profile.hired_at is None:
            profile.hired_at = request.now
        profile.terminated_at = None
        profile.updated_at = request.now

        assignment_id = uuid4()
        assignment = EmployeeAssignment(
            id=assignment_id,
            company_id=invitation.company_id,
            employee_profile_id=invitation.employee_profile_id,
            position_id=invitation.position_id,
            access_profile_id=invitation.access_profile_id,
            scope_type=invitation.scope_type,
            is_primary=True,
            status="active",
            starts_at=request.now,
            ends_at=None,
            revoked_at=None,
            revoked_by_account_id=None,
            revoke_reason=None,
            legacy_employee_id=None,
            created_at=request.now,
            updated_at=request.now,
        )
        self._session.add(assignment)
        await self._session.flush()
        self._session.add_all(
            [
                AssignmentVenue(
                    assignment_id=assignment_id,
                    venue_id=venue_id,
                    company_id=invitation.company_id,
                    created_at=request.now,
                )
                for venue_id in working_ids
            ]
            + [
                AssignmentScopeVenue(
                    assignment_id=assignment_id,
                    venue_id=venue_id,
                    company_id=invitation.company_id,
                    created_at=request.now,
                )
                for venue_id in scope_ids
            ]
        )

        invitation.status = "accepted"
        invitation.accepted_by_account_id = request.account_id
        invitation.accepted_assignment_id = assignment_id
        invitation.accepted_at = request.now
        invitation.updated_at = request.now

        return AcceptedWorkforceInvitation(
            invitation_id=invitation.id,
            company_id=invitation.company_id,
            employee_profile_id=invitation.employee_profile_id,
            employee_assignment_id=assignment_id,
            position_id=invitation.position_id,
            access_profile_id=invitation.access_profile_id,
            scope_type=invitation.scope_type,
            working_venue_ids=working_ids,
            scope_venue_ids=scope_ids,
        )

    async def _validate_acceptance_objects(self, invitation: Invitation) -> str:
        company = (
            await self._session.execute(
                select(Company.id)
                .where(
                    Company.id == invitation.company_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        position = (
            await self._session.execute(
                select(Position.id)
                .where(
                    Position.id == invitation.position_id,
                    Position.company_id == invitation.company_id,
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        maximum_scope = (
            await self._session.execute(
                select(AccessProfile.maximum_scope)
                .where(
                    AccessProfile.id == invitation.access_profile_id,
                    AccessProfile.company_id == invitation.company_id,
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if company is None or position is None or maximum_scope is None:
            raise InvitationNoLongerApplicable(
                "invitation references unavailable business objects"
            )
        return maximum_scope

    async def _locked_invitation_venues(
        self, invitation: Invitation
    ) -> tuple[set[UUID], set[UUID]]:
        working_ids = set(
            (
                await self._session.execute(
                    select(InvitationVenue.venue_id)
                    .where(InvitationVenue.invitation_id == invitation.id)
                    .with_for_update()
                )
            ).scalars()
        )
        scope_ids = set(
            (
                await self._session.execute(
                    select(InvitationScopeVenue.venue_id)
                    .where(InvitationScopeVenue.invitation_id == invitation.id)
                    .with_for_update()
                )
            ).scalars()
        )
        venue_ids = working_ids | scope_ids
        if venue_ids:
            valid_ids = set(
                (
                    await self._session.execute(
                        select(Venue.id)
                        .where(
                            Venue.id.in_(venue_ids),
                            Venue.company_id == invitation.company_id,
                            Venue.deleted_at.is_(None),
                            Venue.status != "closed",
                        )
                        .with_for_update()
                    )
                ).scalars()
            )
            if valid_ids != venue_ids:
                raise InvitationNoLongerApplicable(
                    "invitation references unavailable venues"
                )
        return working_ids, scope_ids

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
