"""Owner-controlled Venue and employee access management for Account companies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from uuid import UUID, uuid5

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.company import Company
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.position import Position
from app.infra.database.models.venue import Venue
from app.internal.services.access_decision_service import AccessDecisionService


_NAMESPACE = UUID("907fb82d-1f0a-46ad-88fb-75b873cf34d3")
_CODE_PARTS = re.compile(r"[^a-z0-9]+")
MANAGER_PERMISSIONS = (
    "assessment.assignment.manage",
    "assessment.assignment.read",
    "assessment.template.read",
    "employee.activate",
    "employee.manage",
    "employee.view",
    "invitation.manage",
    "position.manage",
    "task.manage",
    "task.read",
    "task.review",
    "venue.view",
)


class OrganizationAccessError(Exception):
    pass


class OrganizationAccessNotFound(OrganizationAccessError):
    pass


class OrganizationAccessInvalid(OrganizationAccessError):
    pass


class OrganizationAccessConflict(OrganizationAccessError):
    pass


@dataclass(frozen=True)
class CreateOrganizationVenue:
    actor_account_id: UUID
    company_id: UUID
    request_id: UUID
    name: str
    timezone: str | None
    now: datetime


@dataclass(frozen=True)
class ReplaceEmployeeAccess:
    actor_account_id: UUID
    company_id: UUID
    employee_profile_id: UUID
    profile: str
    venue_ids: tuple[UUID, ...]
    expected_updated_at: datetime
    now: datetime


@dataclass(frozen=True)
class ReplaceEmployeePosition:
    actor_account_id: UUID
    company_id: UUID
    employee_profile_id: UUID
    position_id: UUID
    expected_updated_at: datetime
    now: datetime


class AccountOrganizationAccessService:
    """Mutate one owner-authorized organization aggregate per caller transaction."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._access = AccessDecisionService(session)

    async def create_venue(self, command: CreateOrganizationVenue) -> dict[str, object]:
        now = self._aware(command.now, "now")
        name = self._text(command.name, "name", 255)
        timezone_name = (
            self._text(command.timezone, "timezone", 100)
            if command.timezone is not None
            else None
        )
        await self._require_owner(command.actor_account_id, command.company_id, lock=True)
        venue_id = uuid5(
            _NAMESPACE, f"organization-venue-v1:{command.company_id}:{command.request_id}"
        )
        existing = await self._session.get(Venue, venue_id)
        if existing is not None:
            if (
                existing.company_id != command.company_id
                or existing.name != name
                or existing.timezone != timezone_name
                or existing.deleted_at is not None
                or existing.meta.get("owner_request_id") != str(command.request_id)
            ):
                raise OrganizationAccessConflict("venue request is unavailable")
            return self._venue(existing, created=False)
        slug = self._slug(name)
        code = f"{slug[:82]}-{command.request_id.hex[:12]}"
        venue = Venue(
            id=venue_id,
            company_id=command.company_id,
            legacy_organization_id=None,
            name=name,
            code=code,
            concept=None,
            address=None,
            phone=None,
            timezone=timezone_name,
            status="active",
            meta={"source": "owner_venue_v1", "owner_request_id": str(command.request_id)},
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(venue)
                await self._session.flush()
        except IntegrityError as error:
            concurrent = await self._session.get(Venue, venue_id)
            if concurrent is None:
                raise OrganizationAccessConflict("venue request is unavailable") from error
            if (
                concurrent.company_id != command.company_id
                or concurrent.name != name
                or concurrent.timezone != timezone_name
                or concurrent.meta.get("owner_request_id") != str(command.request_id)
            ):
                raise OrganizationAccessConflict("venue request is unavailable") from error
            return self._venue(concurrent, created=False)
        return self._venue(venue, created=True)

    async def list_venues(
        self, actor_account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, object]]:
        checked_now = self._aware(now, "now")
        _, company_wide, venue_ids = await self._authority_scope(
            actor_account_id, company_id, "venue.view", checked_now
        )
        rows = (
            await self._session.execute(
                select(Venue)
                .where(
                    Venue.company_id == company_id,
                    *([] if company_wide else [Venue.id.in_(venue_ids)]),
                    Venue.deleted_at.is_(None),
                    Venue.status != "closed",
                )
                .order_by(Venue.name, Venue.id)
            )
        ).scalars()
        return [self._venue(row, created=False) for row in rows]

    async def list_employees(
        self, actor_account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, object]]:
        checked_now = self._aware(now, "now")
        owner_id, company_wide, visible_venues = await self._authority_scope(
            actor_account_id, company_id, "employee.view", checked_now
        )
        _, manage_company_wide, manageable_venues = await self._authority_scope(
            actor_account_id,
            company_id,
            "employee.manage",
            checked_now,
            required=False,
        )
        rows = (
            await self._session.execute(
                select(EmployeeProfile, EmployeeAssignment, AccessProfile, Position)
                .join(
                    EmployeeAssignment,
                    (EmployeeAssignment.employee_profile_id == EmployeeProfile.id)
                    & (EmployeeAssignment.company_id == EmployeeProfile.company_id),
                )
                .join(
                    AccessProfile,
                    (AccessProfile.id == EmployeeAssignment.access_profile_id)
                    & (AccessProfile.company_id == EmployeeAssignment.company_id),
                )
                .join(
                    Position,
                    (Position.id == EmployeeAssignment.position_id)
                    & (Position.company_id == EmployeeAssignment.company_id),
                )
                .where(
                    EmployeeProfile.company_id == company_id,
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeAssignment.status == "active",
                    EmployeeAssignment.is_primary.is_(True),
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.starts_at <= checked_now,
                    (EmployeeAssignment.ends_at.is_(None))
                    | (EmployeeAssignment.ends_at > checked_now),
                )
                .order_by(EmployeeProfile.full_name, EmployeeProfile.id)
            )
        ).all()
        result: list[dict[str, object]] = []
        for profile, assignment, access_profile, position in rows:
            working_venues = await self._working_venue_ids(assignment)
            if not company_wide and not working_venues.intersection(visible_venues):
                continue
            target_owner = profile.account_id == owner_id
            editable = not target_owner and (
                manage_company_wide
                or (bool(working_venues) and working_venues <= manageable_venues)
            )
            result.append(
                await self._access_projection(
                    profile,
                    assignment,
                    access_profile,
                    position,
                    target_owner,
                    editable,
                )
            )
        return result

    async def employee_access(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        employee_profile_id: UUID,
        now: datetime,
    ) -> dict[str, object]:
        checked_now = self._aware(now, "now")
        owner_id, company_wide, visible_venues = await self._authority_scope(
            actor_account_id, company_id, "employee.view", checked_now
        )
        _, manage_company_wide, manageable_venues = await self._authority_scope(
            actor_account_id,
            company_id,
            "employee.manage",
            checked_now,
            required=False,
        )
        profile, assignment, access_profile, position = await self._employee_assignment(
            company_id, employee_profile_id, checked_now, lock=False
        )
        working_venues = await self._working_venue_ids(assignment)
        if not company_wide and not working_venues.intersection(visible_venues):
            raise OrganizationAccessNotFound("employee access is unavailable")
        target_owner = profile.account_id == owner_id
        editable = not target_owner and (
            manage_company_wide
            or (bool(working_venues) and working_venues <= manageable_venues)
        )
        return await self._access_projection(
            profile,
            assignment,
            access_profile,
            position,
            target_owner,
            editable,
        )

    async def replace_employee_access(
        self, command: ReplaceEmployeeAccess
    ) -> dict[str, object]:
        now = self._aware(command.now, "now")
        expected = self._aware(command.expected_updated_at, "expected_updated_at")
        profile, assignment, _, position = await self._employee_assignment(
            command.company_id, command.employee_profile_id, now, lock=True
        )
        await self._require_employee_manager(
            command.actor_account_id,
            command.company_id,
            profile,
            assignment,
            now,
            set(command.venue_ids),
        )
        current_revision = self._aware(assignment.updated_at, "assignment.updated_at")
        if current_revision != expected:
            raise OrganizationAccessConflict("employee access revision is stale")
        normalized_ids = tuple(sorted(set(command.venue_ids), key=str))
        profile_code, scope_type, association = self._profile_contract(
            command.profile, normalized_ids
        )
        await self._validate_venues(command.company_id, normalized_ids)
        access_profile = await self.ensure_access_profile(
            command.company_id, profile_code, now
        )

        await self._session.execute(
            delete(AssignmentVenue).where(
                AssignmentVenue.assignment_id == assignment.id,
                AssignmentVenue.company_id == command.company_id,
            )
        )
        await self._session.execute(
            delete(AssignmentScopeVenue).where(
                AssignmentScopeVenue.assignment_id == assignment.id,
                AssignmentScopeVenue.company_id == command.company_id,
            )
        )
        assignment.access_profile_id = access_profile.id
        assignment.scope_type = scope_type
        assignment.updated_at = now
        if association is not None:
            self._session.add_all(
                [
                    association(
                        assignment_id=assignment.id,
                        venue_id=venue_id,
                        company_id=command.company_id,
                        created_at=now,
                    )
                    for venue_id in normalized_ids
                ]
            )
        await self._session.flush()
        return await self._access_projection(
            profile, assignment, access_profile, position, owner=False, editable=True
        )

    async def replace_employee_position(
        self, command: ReplaceEmployeePosition
    ) -> dict[str, object]:
        now = self._aware(command.now, "now")
        expected = self._aware(command.expected_updated_at, "expected_updated_at")
        profile, assignment, access_profile, current_position = (
            await self._employee_assignment(
                command.company_id, command.employee_profile_id, now, lock=True
            )
        )
        await self._require_employee_manager(
            command.actor_account_id,
            command.company_id,
            profile,
            assignment,
            now,
            None,
        )
        current_revision = self._aware(assignment.updated_at, "assignment.updated_at")
        if current_revision != expected:
            raise OrganizationAccessConflict("employee position revision is stale")
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
                    AccessProfile.code != "owner",
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise OrganizationAccessNotFound("organization resource not found")
        position, _ = row
        if position.id == current_position.id:
            return await self._access_projection(
                profile,
                assignment,
                access_profile,
                current_position,
                owner=False,
                editable=True,
            )
        assignment.position_id = position.id
        assignment.updated_at = now
        await self._session.flush()
        return await self._access_projection(
            profile, assignment, access_profile, position, owner=False, editable=True
        )

    async def _authority_scope(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        permission: str,
        now: datetime,
        *,
        required: bool = True,
    ) -> tuple[UUID, bool, set[UUID]]:
        owner_id = (
            await self._session.execute(
                select(Company.owner_account_id).where(
                    Company.id == company_id,
                    Company.status == "active",
                    Company.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if owner_id is None:
            raise OrganizationAccessNotFound("organization resource not found")
        if actor_account_id == owner_id:
            return owner_id, True, set()
        company_wide = await self._access.can_in_company(
            actor_account_id, company_id, permission, now
        )
        venue_ids = set(
            await self._access.list_accessible_venue_ids(
                actor_account_id, company_id, permission, now
            )
        )
        if required and not company_wide and not venue_ids:
            raise OrganizationAccessNotFound("organization resource not found")
        return owner_id, company_wide, venue_ids

    async def _working_venue_ids(
        self, assignment: EmployeeAssignment
    ) -> set[UUID]:
        return set(
            (
                await self._session.execute(
                    select(AssignmentVenue.venue_id).where(
                        AssignmentVenue.assignment_id == assignment.id,
                        AssignmentVenue.company_id == assignment.company_id,
                    )
                )
            ).scalars()
        )

    async def _require_employee_manager(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        profile: EmployeeProfile,
        assignment: EmployeeAssignment,
        now: datetime,
        requested_venue_ids: set[UUID] | None,
    ) -> None:
        owner_id, company_wide, manageable_venues = await self._authority_scope(
            actor_account_id, company_id, "employee.manage", now
        )
        if profile.account_id == owner_id:
            raise OrganizationAccessNotFound("employee access is unavailable")
        if company_wide:
            return
        current_venues = await self._working_venue_ids(assignment)
        if not current_venues or not current_venues <= manageable_venues:
            raise OrganizationAccessNotFound("employee access is unavailable")
        if requested_venue_ids is not None and not requested_venue_ids <= manageable_venues:
            raise OrganizationAccessNotFound("organization resource not found")

    async def _require_owner(
        self, actor_account_id: UUID, company_id: UUID, *, lock: bool
    ) -> UUID:
        statement = select(Company.owner_account_id).where(
            Company.id == company_id,
            Company.owner_account_id == actor_account_id,
            Company.status == "active",
            Company.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        owner_id = (await self._session.execute(statement)).scalar_one_or_none()
        if owner_id is None:
            raise OrganizationAccessNotFound("organization resource not found")
        return owner_id

    async def _employee_assignment(
        self,
        company_id: UUID,
        employee_profile_id: UUID,
        now: datetime,
        *,
        lock: bool,
    ) -> tuple[EmployeeProfile, EmployeeAssignment, AccessProfile, Position]:
        if lock:
            assignment = (
                await self._session.execute(
                    select(EmployeeAssignment)
                    .where(
                        EmployeeAssignment.company_id == company_id,
                        EmployeeAssignment.employee_profile_id == employee_profile_id,
                        EmployeeAssignment.is_primary.is_(True),
                        EmployeeAssignment.status == "active",
                        EmployeeAssignment.deleted_at.is_(None),
                        EmployeeAssignment.starts_at <= now,
                        (EmployeeAssignment.ends_at.is_(None))
                        | (EmployeeAssignment.ends_at > now),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if assignment is None:
                raise OrganizationAccessNotFound("employee access is unavailable")
            profile = (
                await self._session.execute(
                    select(EmployeeProfile).where(
                        EmployeeProfile.id == assignment.employee_profile_id,
                        EmployeeProfile.company_id == company_id,
                        EmployeeProfile.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            access_profile = (
                await self._session.execute(
                    select(AccessProfile).where(
                        AccessProfile.id == assignment.access_profile_id,
                        AccessProfile.company_id == company_id,
                        AccessProfile.is_active.is_(True),
                        AccessProfile.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            position = (
                await self._session.execute(
                    select(Position).where(
                        Position.id == assignment.position_id,
                        Position.company_id == company_id,
                        Position.is_active.is_(True),
                        Position.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if profile is None or access_profile is None or position is None:
                raise OrganizationAccessNotFound("employee access is unavailable")
            return profile, assignment, access_profile, position
        statement = (
            select(EmployeeProfile, EmployeeAssignment, AccessProfile, Position)
            .join(
                EmployeeAssignment,
                (EmployeeAssignment.employee_profile_id == EmployeeProfile.id)
                & (EmployeeAssignment.company_id == EmployeeProfile.company_id),
            )
            .join(
                AccessProfile,
                (AccessProfile.id == EmployeeAssignment.access_profile_id)
                & (AccessProfile.company_id == EmployeeAssignment.company_id),
            )
            .join(
                Position,
                (Position.id == EmployeeAssignment.position_id)
                & (Position.company_id == EmployeeAssignment.company_id),
            )
            .where(
                EmployeeProfile.id == employee_profile_id,
                EmployeeProfile.company_id == company_id,
                EmployeeProfile.deleted_at.is_(None),
                EmployeeAssignment.company_id == company_id,
                EmployeeAssignment.is_primary.is_(True),
                EmployeeAssignment.status == "active",
                EmployeeAssignment.deleted_at.is_(None),
                EmployeeAssignment.starts_at <= now,
                (EmployeeAssignment.ends_at.is_(None))
                | (EmployeeAssignment.ends_at > now),
                AccessProfile.is_active.is_(True),
                AccessProfile.deleted_at.is_(None),
                Position.is_active.is_(True),
                Position.deleted_at.is_(None),
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            raise OrganizationAccessNotFound("employee access is unavailable")
        return row

    async def ensure_access_profile(
        self, company_id: UUID, code: str, now: datetime
    ) -> AccessProfile:
        """Return the canonical system profile, adding only required permissions."""
        contract = {
            "employee": ("Сотрудник", "working_venues", ("venue.view",)),
            "venue-manager": ("Менеджер ресторанов", "explicit_venues", MANAGER_PERMISSIONS),
            "organization-manager": ("Менеджер организации", "company", MANAGER_PERMISSIONS),
        }[code]
        expected_id = uuid5(_NAMESPACE, f"organization-access-v1:{company_id}:{code}")
        profile = (
            await self._session.execute(
                select(AccessProfile).where(
                    AccessProfile.company_id == company_id,
                    AccessProfile.code == code,
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if profile is None:
            profile = AccessProfile(
                id=expected_id,
                company_id=company_id,
                name=contract[0],
                code=code,
                description="Системный профиль RestOS",
                maximum_scope=contract[1],
                is_system=True,
                is_active=True,
                version=1,
                created_at=now,
                updated_at=now,
            )
            self._session.add(profile)
            await self._session.flush()
        elif (
            not profile.is_system
            or profile.maximum_scope != contract[1]
            or (code != "employee" and profile.id != expected_id)
        ):
            raise OrganizationAccessConflict("access profile is incompatible")
        existing = set(
            (
                await self._session.execute(
                    select(AccessProfilePermission.permission_code).where(
                        AccessProfilePermission.access_profile_id == profile.id
                    )
                )
            ).scalars()
        )
        required = set(contract[2])
        if existing - required:
            raise OrganizationAccessConflict("access profile is incompatible")
        self._session.add_all(
            [
                AccessProfilePermission(
                    access_profile_id=profile.id,
                    permission_code=permission,
                    created_at=now,
                )
                for permission in sorted(required - existing)
            ]
        )
        await self._session.flush()
        return profile

    async def _validate_venues(self, company_id: UUID, venue_ids: tuple[UUID, ...]) -> None:
        if not venue_ids:
            return
        found = set(
            (
                await self._session.execute(
                    select(Venue.id).where(
                        Venue.id.in_(venue_ids),
                        Venue.company_id == company_id,
                        Venue.status == "active",
                        Venue.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        if found != set(venue_ids):
            raise OrganizationAccessNotFound("organization resource not found")

    async def _access_projection(
        self,
        profile: EmployeeProfile,
        assignment: EmployeeAssignment,
        access_profile: AccessProfile,
        position: Position,
        owner: bool,
        editable: bool | None = None,
    ) -> dict[str, object]:
        if owner:
            profile_name = "owner"
            venue_ids: list[UUID] = []
        else:
            profile_name = {
                ("employee", "self"): "employee_unassigned",
                ("employee", "working_venues"): "employee_venue",
                ("venue-manager", "explicit_venues"): "venue_manager",
                ("organization-manager", "company"): "organization_manager",
            }.get((access_profile.code, assignment.scope_type), "unsupported")
            association = (
                AssignmentVenue
                if assignment.scope_type == "working_venues"
                else AssignmentScopeVenue
            )
            venue_ids = (
                sorted(
                    set(
                        (
                            await self._session.execute(
                                select(association.venue_id).where(
                                    association.assignment_id == assignment.id,
                                    association.company_id == assignment.company_id,
                                )
                            )
                        ).scalars()
                    ),
                    key=str,
                )
                if assignment.scope_type in {"working_venues", "explicit_venues"}
                else []
            )
        return {
            "employee_profile_id": profile.id,
            "display_name": profile.full_name,
            "employment_status": profile.employment_status,
            "position_id": position.id,
            "position_name": position.name,
            "profile": profile_name,
            "venue_ids": venue_ids,
            "revision": assignment.updated_at,
            "editable": (not owner if editable is None else editable)
            and profile_name != "unsupported",
        }

    @staticmethod
    def _profile_contract(profile: str, venue_ids: tuple[UUID, ...]):
        if profile == "employee_unassigned" and not venue_ids:
            return "employee", "self", None
        if profile == "employee_venue" and len(venue_ids) == 1:
            return "employee", "working_venues", AssignmentVenue
        if profile == "venue_manager" and venue_ids:
            return "venue-manager", "explicit_venues", AssignmentScopeVenue
        if profile == "organization_manager" and not venue_ids:
            return "organization-manager", "company", None
        raise OrganizationAccessInvalid("invalid access profile scope")

    @staticmethod
    def _venue(venue: Venue, *, created: bool) -> dict[str, object]:
        return {
            "created": created,
            "venue_id": venue.id,
            "name": venue.name,
            "code": venue.code,
            "timezone": venue.timezone,
            "status": venue.status,
        }

    @staticmethod
    def _text(value: str | None, name: str, maximum: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise OrganizationAccessInvalid(f"{name} is invalid")
        return value.strip()

    @staticmethod
    def _slug(value: str) -> str:
        slug = _CODE_PARTS.sub("-", value.casefold().encode("ascii", "ignore").decode()).strip("-")
        return slug or "venue"

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise OrganizationAccessInvalid(f"{name} must be timezone-aware")
        return value.astimezone(timezone.utc)
