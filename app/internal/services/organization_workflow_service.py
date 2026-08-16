"""Tenant-safe organization structure, reusable onboarding, and task workflows."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import re
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.access_profile import AccessProfile
from app.infra.database.models.account import Account
from app.infra.database.models.assessment_attempt import (
    AssessmentAssignment,
    AssessmentAttempt,
)
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.employee_profile import (
    EmployeeBirthDateAudit,
    EmployeeProfile,
)
from app.infra.database.models.organization_workflow import (
    GroupInvitation,
    GroupInvitationRegistration,
    Task,
    TaskAssignment,
    TaskEvent,
    TaskPhoto,
)
from app.infra.database.models.position import Position
from app.internal.services.access_decision_service import AccessDecisionService
from app.internal.services.account_organization_access_service import (
    AccountOrganizationAccessService,
)


_NAMESPACE = UUID("2890391e-b4bd-4939-b44e-804be4709305")
_CODE_PARTS = re.compile(r"[^a-z0-9]+")
_PRESET_TO_PROFILE = {
    "employee_unassigned": ("employee", "self"),
    "employee_venue": ("employee", "working_venues"),
    "venue_manager": ("venue-manager", "explicit_venues"),
    "organization_manager": ("organization-manager", "company"),
}


class OrganizationWorkflowError(Exception):
    """Base class for controlled workflow failures."""


class OrganizationWorkflowNotFound(OrganizationWorkflowError):
    pass


class OrganizationWorkflowInvalid(OrganizationWorkflowError):
    pass


class OrganizationWorkflowConflict(OrganizationWorkflowError):
    pass


class OrganizationWorkflowUnavailable(OrganizationWorkflowError):
    pass


@dataclass(frozen=True)
class CreatePosition:
    actor_account_id: UUID
    company_id: UUID
    request_id: UUID
    name: str
    description: str | None
    access_preset: str
    sort_order: int
    now: datetime


@dataclass(frozen=True)
class CreateGroupInvitation:
    actor_account_id: UUID
    company_id: UUID
    request_id: UUID
    venue_id: UUID
    position_id: UUID
    label: str
    expires_at: datetime
    max_registrations: int
    now: datetime


@dataclass(frozen=True)
class JoinGroupInvitation:
    actor_account_id: UUID
    token: str
    request_id: UUID
    first_name: str
    last_name: str
    birth_date: date
    now: datetime


@dataclass(frozen=True)
class UpdateEmployeeBirthDate:
    actor_account_id: UUID
    company_id: UUID
    employee_profile_id: UUID
    expected_birth_date: date | None
    birth_date: date
    now: datetime


@dataclass(frozen=True)
class ActivateGroupRegistration:
    actor_account_id: UUID
    company_id: UUID
    registration_id: UUID
    now: datetime


@dataclass(frozen=True)
class CreateTaskDraft:
    actor_account_id: UUID
    company_id: UUID
    venue_id: UUID
    request_id: UUID
    assessment_attempt_id: UUID | None
    title: str
    description: str | None
    now: datetime


@dataclass(frozen=True)
class UpdateTaskDraft:
    actor_account_id: UUID
    company_id: UUID
    task_id: UUID
    expected_version: int
    title: str
    description: str | None
    now: datetime


@dataclass(frozen=True)
class CancelTask:
    actor_account_id: UUID
    company_id: UUID
    task_id: UUID
    expected_version: int
    now: datetime


@dataclass(frozen=True)
class DispatchTask:
    actor_account_id: UUID
    company_id: UUID
    task_id: UUID
    employee_profile_ids: tuple[UUID, ...]
    expected_version: int
    now: datetime


@dataclass(frozen=True)
class TransitionTaskAssignment:
    actor_account_id: UUID
    company_id: UUID
    task_assignment_id: UUID
    action: str
    expected_version: int
    now: datetime


class OrganizationWorkflowService:
    """Apply organization workflow mutations within the caller transaction."""

    def __init__(self, session: AsyncSession, *, invitation_pepper: bytes):
        if not isinstance(invitation_pepper, bytes) or len(invitation_pepper) < 32:
            raise ValueError("invitation_pepper must contain at least 32 bytes")
        self._session = session
        self._invitation_pepper = invitation_pepper
        self._access = AccessDecisionService(session)

    async def list_access_presets(self) -> list[dict[str, object]]:
        return [
            {
                "code": "owner",
                "title": "Собственник",
                "scope": "company",
                "assignable": False,
                "description": "Полное управление организацией и всеми ресторанами.",
            },
            {
                "code": "organization_manager",
                "title": "Управление всей организацией",
                "scope": "company",
                "assignable": True,
                "description": "Сотрудники, оценки, аналитика и задачи во всей организации.",
            },
            {
                "code": "venue_manager",
                "title": "Управление выбранными ресторанами",
                "scope": "explicit_venues",
                "assignable": True,
                "description": "Управление только явно разрешёнными ресторанами.",
            },
            {
                "code": "employee_venue",
                "title": "Обычный сотрудник",
                "scope": "working_venues",
                "assignable": True,
                "description": "Личные оценки и задачи в рабочем ресторане.",
            },
            {
                "code": "employee_unassigned",
                "title": "Сотрудник без привязки",
                "scope": "self",
                "assignable": True,
                "description": "Только собственные оценки и задачи без ресторана.",
            },
        ]

    async def list_positions(
        self, actor_account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, object]]:
        await self._require_company_capability(
            actor_account_id, company_id, "position.manage", now
        )
        rows = (
            await self._session.execute(
                select(Position, AccessProfile)
                .join(
                    AccessProfile,
                    (AccessProfile.id == Position.default_access_profile_id)
                    & (AccessProfile.company_id == Position.company_id),
                )
                .where(
                    Position.company_id == company_id,
                    Position.deleted_at.is_(None),
                    Position.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                    AccessProfile.is_active.is_(True),
                )
                .order_by(Position.sort_order, Position.name, Position.id)
            )
        ).all()
        return [self._position(position, profile) for position, profile in rows]

    async def create_position(self, command: CreatePosition) -> dict[str, object]:
        now = self._aware(command.now, "now")
        await self._require_company_capability(
            command.actor_account_id, command.company_id, "position.manage", now
        )
        name = self._text(command.name, "name", 255)
        description = self._optional_text(command.description, "description", 2000)
        if command.access_preset not in _PRESET_TO_PROFILE:
            raise OrganizationWorkflowInvalid("access_preset is invalid")
        if isinstance(command.sort_order, bool) or not 0 <= command.sort_order <= 1000:
            raise OrganizationWorkflowInvalid("sort_order is invalid")
        profile_code, default_scope_type = _PRESET_TO_PROFILE[command.access_preset]
        access_profile = await AccountOrganizationAccessService(
            self._session
        ).ensure_access_profile(command.company_id, profile_code, now)
        position_id = uuid5(
            _NAMESPACE,
            f"position-v1:{command.company_id}:{command.request_id}",
        )
        existing = await self._session.get(Position, position_id)
        if existing is not None:
            if (
                existing.company_id != command.company_id
                or existing.name != name
                or existing.description != description
                or existing.default_access_profile_id != access_profile.id
                or existing.default_scope_type != default_scope_type
                or existing.sort_order != command.sort_order
                or existing.deleted_at is not None
            ):
                raise OrganizationWorkflowConflict("position request is unavailable")
            return self._position(existing, access_profile)
        code = f"{self._slug(name)[:82]}-{command.request_id.hex[:12]}"
        position = Position(
            id=position_id,
            company_id=command.company_id,
            name=name,
            code=code,
            description=description,
            default_access_profile_id=access_profile.id,
            default_scope_type=default_scope_type,
            is_active=True,
            sort_order=command.sort_order,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(position)
                await self._session.flush()
        except IntegrityError as error:
            concurrent = await self._session.get(Position, position_id)
            if concurrent is None:
                raise OrganizationWorkflowConflict(
                    "position request is unavailable"
                ) from error
            if (
                concurrent.company_id != command.company_id
                or concurrent.name != name
                or concurrent.description != description
                or concurrent.default_access_profile_id != access_profile.id
                or concurrent.default_scope_type != default_scope_type
                or concurrent.sort_order != command.sort_order
                or concurrent.deleted_at is not None
            ):
                raise OrganizationWorkflowConflict(
                    "position request is unavailable"
                ) from error
            return self._position(concurrent, access_profile)
        return self._position(position, access_profile)

    async def create_group_invitation(
        self, command: CreateGroupInvitation
    ) -> dict[str, object]:
        now = self._aware(command.now, "now")
        expires_at = self._aware(command.expires_at, "expires_at")
        if not now + timedelta(minutes=15) <= expires_at <= now + timedelta(days=30):
            raise OrganizationWorkflowInvalid("invitation expiry is invalid")
        if (
            isinstance(command.max_registrations, bool)
            or not 1 <= command.max_registrations <= 200
        ):
            raise OrganizationWorkflowInvalid("invitation capacity is invalid")
        label = self._text(command.label, "label", 160)
        await self._require_venue_capability(
            command.actor_account_id,
            command.company_id,
            command.venue_id,
            "invitation.manage",
            now,
        )
        position, access_profile = await self._available_position(
            command.company_id, command.position_id
        )
        if position.default_scope_type == "self":
            raise OrganizationWorkflowInvalid(
                "group invitation position requires a venue-bound preset"
            )
        token = self._invitation_token(command.company_id, command.request_id)
        digest = self._invitation_digest(token)
        invitation_id = uuid5(
            _NAMESPACE,
            f"group-invitation-v1:{command.company_id}:{command.request_id}",
        )
        existing = (
            await self._session.execute(
                select(GroupInvitation).where(
                    GroupInvitation.company_id == command.company_id,
                    GroupInvitation.request_id == command.request_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            self._same_invitation(
                existing, command, position, access_profile, label, expires_at, digest
            )
            return self._group_invitation(existing, token)
        invitation = GroupInvitation(
            id=invitation_id,
            company_id=command.company_id,
            venue_id=command.venue_id,
            position_id=position.id,
            access_profile_id=access_profile.id,
            created_by_account_id=command.actor_account_id,
            request_id=command.request_id,
            token_digest=digest,
            label=label,
            status="active",
            max_registrations=command.max_registrations,
            registration_count=0,
            expires_at=expires_at,
            revoked_at=None,
            revoked_by_account_id=None,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(invitation)
                await self._session.flush()
        except IntegrityError as error:
            concurrent = (
                await self._session.execute(
                    select(GroupInvitation).where(
                        GroupInvitation.company_id == command.company_id,
                        GroupInvitation.request_id == command.request_id,
                    )
                )
            ).scalar_one_or_none()
            if concurrent is None:
                raise OrganizationWorkflowConflict(
                    "invitation request is unavailable"
                ) from error
            self._same_invitation(
                concurrent,
                command,
                position,
                access_profile,
                label,
                expires_at,
                digest,
            )
            return self._group_invitation(concurrent, token)
        return self._group_invitation(invitation, token)

    async def list_group_invitations(
        self, actor_account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, object]]:
        checked_now = self._aware(now, "now")
        venue_ids = await self._access.list_accessible_venue_ids(
            actor_account_id, company_id, "invitation.manage", checked_now
        )
        if not venue_ids:
            raise OrganizationWorkflowNotFound("organization resource is unavailable")
        invitations = (
            await self._session.execute(
                select(GroupInvitation)
                .where(
                    GroupInvitation.company_id == company_id,
                    GroupInvitation.venue_id.in_(venue_ids),
                )
                .order_by(GroupInvitation.created_at.desc(), GroupInvitation.id)
            )
        ).scalars()
        return [self._group_invitation(row, None) for row in invitations]

    async def list_pending_registrations(
        self, actor_account_id: UUID, company_id: UUID, now: datetime
    ) -> list[dict[str, object]]:
        checked_now = self._aware(now, "now")
        venue_ids = await self._access.list_accessible_venue_ids(
            actor_account_id, company_id, "employee.activate", checked_now
        )
        if not venue_ids:
            raise OrganizationWorkflowNotFound("organization resource is unavailable")
        rows = (
            await self._session.execute(
                select(
                    GroupInvitationRegistration,
                    EmployeeProfile,
                    GroupInvitation,
                )
                .join(
                    EmployeeProfile,
                    (
                        EmployeeProfile.id
                        == GroupInvitationRegistration.employee_profile_id
                    )
                    & (
                        EmployeeProfile.company_id
                        == GroupInvitationRegistration.company_id
                    ),
                )
                .join(
                    GroupInvitation,
                    (
                        GroupInvitation.id
                        == GroupInvitationRegistration.group_invitation_id
                    )
                    & (
                        GroupInvitation.company_id
                        == GroupInvitationRegistration.company_id
                    ),
                )
                .where(
                    GroupInvitationRegistration.company_id == company_id,
                    GroupInvitationRegistration.status == "pending_activation",
                    GroupInvitation.venue_id.in_(venue_ids),
                    EmployeeProfile.deleted_at.is_(None),
                )
                .order_by(
                    GroupInvitationRegistration.created_at,
                    GroupInvitationRegistration.id,
                )
            )
        ).all()
        return [
            self._registration(registration, profile, invitation)
            for registration, profile, invitation in rows
        ]

    async def revoke_group_invitation(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        invitation_id: UUID,
        now: datetime,
    ) -> dict[str, object]:
        checked_now = self._aware(now, "now")
        invitation = await self._invitation_by_id(company_id, invitation_id, lock=True)
        await self._require_venue_capability(
            actor_account_id,
            company_id,
            invitation.venue_id,
            "invitation.manage",
            checked_now,
        )
        if invitation.status == "revoked":
            return self._group_invitation(invitation, None)
        if invitation.status != "active":
            raise OrganizationWorkflowUnavailable("invitation is unavailable")
        invitation.status = "revoked"
        invitation.revoked_at = checked_now
        invitation.revoked_by_account_id = actor_account_id
        invitation.updated_at = checked_now
        await self._session.flush()
        return self._group_invitation(invitation, None)

    async def join_group_invitation(
        self, command: JoinGroupInvitation
    ) -> dict[str, object]:
        now = self._aware(command.now, "now")
        token = self._token(command.token)
        first_name = self._text(command.first_name, "first_name", 120)
        last_name = self._text(command.last_name, "last_name", 120)
        birth_date = self._birth_date(command.birth_date, now)
        account = await self._session.get(Account, command.actor_account_id)
        if (
            account is None
            or account.status != "active"
            or account.deleted_at is not None
        ):
            raise OrganizationWorkflowNotFound("group invitation is unavailable")
        digest = self._invitation_digest(token)
        invitation = (
            await self._session.execute(
                select(GroupInvitation)
                .where(
                    GroupInvitation.token_digest == digest,
                    GroupInvitation.status == "active",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            invitation is None
            or not hmac.compare_digest(invitation.token_digest, digest)
            or invitation.expires_at <= now
        ):
            raise OrganizationWorkflowNotFound("group invitation is unavailable")
        existing = (
            await self._session.execute(
                select(GroupInvitationRegistration, EmployeeProfile)
                .join(
                    EmployeeProfile,
                    (
                        EmployeeProfile.id
                        == GroupInvitationRegistration.employee_profile_id
                    )
                    & (
                        EmployeeProfile.company_id
                        == GroupInvitationRegistration.company_id
                    ),
                )
                .where(
                    GroupInvitationRegistration.group_invitation_id == invitation.id,
                    GroupInvitationRegistration.request_id == command.request_id,
                )
            )
        ).one_or_none()
        if existing is not None:
            registration, profile = existing
            if registration.account_id != command.actor_account_id:
                raise OrganizationWorkflowNotFound("group invitation is unavailable")
            return self._registration(registration, profile, invitation)
        member_exists = (
            await self._session.execute(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.company_id == invitation.company_id,
                    EmployeeProfile.account_id == command.actor_account_id,
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if member_exists is not None:
            raise OrganizationWorkflowConflict("account membership already exists")
        if invitation.registration_count >= invitation.max_registrations:
            raise OrganizationWorkflowUnavailable("invitation capacity is exhausted")
        registration_id = uuid5(
            _NAMESPACE,
            f"group-registration-v1:{invitation.id}:{command.request_id}",
        )
        profile_id = uuid5(_NAMESPACE, f"group-profile-v1:{registration_id}")
        profile = EmployeeProfile(
            id=profile_id,
            company_id=invitation.company_id,
            account_id=command.actor_account_id,
            full_name=f"{first_name} {last_name}",
            email=None,
            phone=None,
            birth_date=birth_date,
            employment_status="pending_activation",
            hired_at=None,
            terminated_at=None,
            meta={"source": "group_invitation_v1"},
            created_at=now,
            updated_at=now,
        )
        registration = GroupInvitationRegistration(
            id=registration_id,
            group_invitation_id=invitation.id,
            company_id=invitation.company_id,
            employee_profile_id=profile.id,
            account_id=command.actor_account_id,
            request_id=command.request_id,
            status="pending_activation",
            activated_at=None,
            activated_by_account_id=None,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add_all([profile, registration])
                invitation.registration_count += 1
                invitation.updated_at = now
                await self._session.flush()
                self._session.add(
                    EmployeeBirthDateAudit(
                        employee_profile_id=profile.id,
                        company_id=profile.company_id,
                        actor_account_id=command.actor_account_id,
                        previous_birth_date=None,
                        new_birth_date=birth_date,
                        source="group_onboarding",
                        changed_at=now,
                    )
                )
                await self._session.flush()
        except IntegrityError as error:
            concurrent = (
                await self._session.execute(
                    select(GroupInvitationRegistration, EmployeeProfile)
                    .join(
                        EmployeeProfile,
                        EmployeeProfile.id
                        == GroupInvitationRegistration.employee_profile_id,
                    )
                    .where(
                        GroupInvitationRegistration.company_id == invitation.company_id,
                        GroupInvitationRegistration.account_id
                        == command.actor_account_id,
                        GroupInvitationRegistration.status != "rejected",
                    )
                )
            ).one_or_none()
            if concurrent is None:
                raise OrganizationWorkflowConflict(
                    "registration request is unavailable"
                ) from error
            return self._registration(concurrent[0], concurrent[1], invitation)
        return self._registration(registration, profile, invitation)

    async def employee_birth_date(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        employee_profile_id: UUID,
        now: datetime,
    ) -> dict[str, object]:
        """Return DOB to its employee or an employee-view principal in scope."""
        checked_now = self._aware(now, "now")
        profile = await self._birth_date_profile(
            company_id, employee_profile_id, lock=False
        )
        await self._require_birth_date_access(
            actor_account_id, profile, "employee.view", checked_now
        )
        return self._birth_date_projection(profile)

    async def update_employee_birth_date(
        self, command: UpdateEmployeeBirthDate
    ) -> dict[str, object]:
        """Replace DOB with a locked compare-and-set and append-only audit."""
        now = self._aware(command.now, "now")
        birth_date = self._birth_date(command.birth_date, now)
        if command.expected_birth_date is not None:
            self._birth_date(command.expected_birth_date, now)
        profile = await self._birth_date_profile(
            command.company_id, command.employee_profile_id, lock=True
        )
        is_self = await self._require_birth_date_access(
            command.actor_account_id, profile, "employee.manage", now
        )
        if profile.birth_date != command.expected_birth_date:
            raise OrganizationWorkflowConflict("birth_date revision is stale")
        if profile.birth_date == birth_date:
            return self._birth_date_projection(profile)
        previous = profile.birth_date
        profile.birth_date = birth_date
        profile.updated_at = now
        self._session.add(
            EmployeeBirthDateAudit(
                employee_profile_id=profile.id,
                company_id=profile.company_id,
                actor_account_id=command.actor_account_id,
                previous_birth_date=previous,
                new_birth_date=birth_date,
                source="employee_update" if is_self else "manager_update",
                changed_at=now,
            )
        )
        await self._session.flush()
        return self._birth_date_projection(profile)

    async def employee_birth_date_audit(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        employee_profile_id: UUID,
        now: datetime,
    ) -> list[dict[str, object]]:
        """Return the restricted chronological DOB audit trail."""
        checked_now = self._aware(now, "now")
        profile = await self._birth_date_profile(
            company_id, employee_profile_id, lock=False
        )
        await self._require_birth_date_access(
            actor_account_id, profile, "employee.view", checked_now
        )
        rows = (
            await self._session.execute(
                select(EmployeeBirthDateAudit)
                .where(
                    EmployeeBirthDateAudit.company_id == company_id,
                    EmployeeBirthDateAudit.employee_profile_id == employee_profile_id,
                )
                .order_by(
                    EmployeeBirthDateAudit.changed_at,
                    EmployeeBirthDateAudit.id,
                )
            )
        ).scalars()
        return [
            {
                "actor_account_id": row.actor_account_id,
                "previous_birth_date": row.previous_birth_date,
                "birth_date": row.new_birth_date,
                "source": row.source,
                "changed_at": row.changed_at,
            }
            for row in rows
        ]

    async def activate_group_registration(
        self, command: ActivateGroupRegistration
    ) -> dict[str, object]:
        now = self._aware(command.now, "now")
        row = (
            await self._session.execute(
                select(
                    GroupInvitationRegistration,
                    GroupInvitation,
                    EmployeeProfile,
                    Position,
                    AccessProfile,
                )
                .join(
                    GroupInvitation,
                    (
                        GroupInvitation.id
                        == GroupInvitationRegistration.group_invitation_id
                    )
                    & (
                        GroupInvitation.company_id
                        == GroupInvitationRegistration.company_id
                    ),
                )
                .join(
                    EmployeeProfile,
                    (
                        EmployeeProfile.id
                        == GroupInvitationRegistration.employee_profile_id
                    )
                    & (
                        EmployeeProfile.company_id
                        == GroupInvitationRegistration.company_id
                    ),
                )
                .join(
                    Position,
                    (Position.id == GroupInvitation.position_id)
                    & (Position.company_id == GroupInvitation.company_id),
                )
                .join(
                    AccessProfile,
                    (AccessProfile.id == GroupInvitation.access_profile_id)
                    & (AccessProfile.company_id == GroupInvitation.company_id),
                )
                .where(
                    GroupInvitationRegistration.id == command.registration_id,
                    GroupInvitationRegistration.company_id == command.company_id,
                )
                .with_for_update(of=GroupInvitationRegistration)
            )
        ).one_or_none()
        if row is None:
            raise OrganizationWorkflowNotFound("registration is unavailable")
        registration, invitation, profile, position, access_profile = row
        await self._require_venue_capability(
            command.actor_account_id,
            command.company_id,
            invitation.venue_id,
            "employee.activate",
            now,
        )
        if registration.status == "active":
            return self._registration(registration, profile, invitation)
        if (
            registration.status != "pending_activation"
            or profile.employment_status != "pending_activation"
            or profile.deleted_at is not None
            or not position.is_active
            or position.deleted_at is not None
            or not access_profile.is_active
            or access_profile.deleted_at is not None
            or position.default_access_profile_id != access_profile.id
            or invitation.registration_count > invitation.max_registrations
        ):
            raise OrganizationWorkflowUnavailable("registration is unavailable")
        preset = self._preset_for_access(access_profile, position.default_scope_type)
        _, scope_type = _PRESET_TO_PROFILE[preset]
        assignment_id = uuid5(_NAMESPACE, f"group-assignment-v1:{registration.id}")
        assignment = EmployeeAssignment(
            id=assignment_id,
            company_id=command.company_id,
            employee_profile_id=profile.id,
            position_id=position.id,
            access_profile_id=access_profile.id,
            scope_type=scope_type,
            is_primary=True,
            status="active",
            starts_at=now,
            ends_at=None,
            revoked_at=None,
            revoked_by_account_id=None,
            revoke_reason=None,
            legacy_employee_id=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(assignment)
        # Models intentionally expose no ORM relationships; flush the parent
        # before adding composite-FK venue rows while keeping one transaction.
        await self._session.flush()
        self._session.add(
            AssignmentVenue(
                assignment_id=assignment.id,
                venue_id=invitation.venue_id,
                company_id=command.company_id,
                created_at=now,
            )
        )
        if scope_type == "explicit_venues":
            self._session.add(
                AssignmentScopeVenue(
                    assignment_id=assignment.id,
                    venue_id=invitation.venue_id,
                    company_id=command.company_id,
                    created_at=now,
                )
            )
        profile.employment_status = "active"
        profile.hired_at = now
        profile.updated_at = now
        registration.status = "active"
        registration.activated_at = now
        registration.activated_by_account_id = command.actor_account_id
        registration.updated_at = now
        await self._session.flush()
        return self._registration(registration, profile, invitation)

    async def create_task_draft(self, command: CreateTaskDraft) -> dict[str, object]:
        now = self._aware(command.now, "now")
        title = self._text(command.title, "title", 255)
        description = self._optional_text(command.description, "description", 4000)
        await self._require_venue_capability(
            command.actor_account_id,
            command.company_id,
            command.venue_id,
            "task.manage",
            now,
        )
        if command.assessment_attempt_id is not None:
            attempt_exists = (
                await self._session.execute(
                    select(AssessmentAttempt.id)
                    .join(
                        AssessmentAssignment,
                        AssessmentAssignment.id == AssessmentAttempt.assignment_id,
                    )
                    .where(
                        AssessmentAttempt.id == command.assessment_attempt_id,
                        AssessmentAssignment.company_id == command.company_id,
                        AssessmentAssignment.venue_id == command.venue_id,
                        AssessmentAttempt.status == "draft",
                    )
                )
            ).scalar_one_or_none()
            if attempt_exists is None:
                raise OrganizationWorkflowNotFound("assessment attempt is unavailable")
        task_id = uuid5(
            _NAMESPACE,
            f"task-v1:{command.actor_account_id}:{command.request_id}",
        )
        existing = (
            await self._session.execute(
                select(Task).where(
                    Task.author_account_id == command.actor_account_id,
                    Task.request_id == command.request_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.company_id != command.company_id
                or existing.venue_id != command.venue_id
                or existing.assessment_attempt_id != command.assessment_attempt_id
                or existing.title != title
                or existing.description != description
            ):
                raise OrganizationWorkflowConflict("task request is unavailable")
            return await self._task(existing)
        task = Task(
            id=task_id,
            company_id=command.company_id,
            venue_id=command.venue_id,
            assessment_attempt_id=command.assessment_attempt_id,
            author_account_id=command.actor_account_id,
            request_id=command.request_id,
            title=title,
            description=description,
            status="draft",
            version=1,
            dispatched_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(task)
        await self._session.flush()
        await self._event(task, command.actor_account_id, "task_created", {}, now)
        return await self._task(task)

    async def list_tasks(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        view: str,
        now: datetime,
    ) -> list[dict[str, object]]:
        checked_now = self._aware(now, "now")
        if view == "mine":
            rows = (
                await self._session.execute(
                    select(Task, TaskAssignment)
                    .join(
                        TaskAssignment,
                        (TaskAssignment.task_id == Task.id)
                        & (TaskAssignment.company_id == Task.company_id),
                    )
                    .join(
                        EmployeeProfile,
                        (EmployeeProfile.id == TaskAssignment.employee_profile_id)
                        & (EmployeeProfile.company_id == TaskAssignment.company_id),
                    )
                    .where(
                        Task.company_id == company_id,
                        EmployeeProfile.account_id == actor_account_id,
                        EmployeeProfile.employment_status == "active",
                        EmployeeProfile.deleted_at.is_(None),
                    )
                    .order_by(Task.updated_at.desc(), Task.id)
                )
            ).all()
            return [await self._task(task, assignment) for task, assignment in rows]
        elif view in {"created", "review"}:
            venue_ids = await self._access.list_accessible_venue_ids(
                actor_account_id, company_id, "task.read", checked_now
            )
            if not venue_ids:
                raise OrganizationWorkflowNotFound("task list is unavailable")
            statement = select(Task).where(
                Task.company_id == company_id,
                Task.venue_id.in_(venue_ids),
            )
            if view == "created":
                statement = statement.where(Task.author_account_id == actor_account_id)
            else:
                statement = (
                    select(Task, TaskAssignment)
                    .join(
                        TaskAssignment,
                        (TaskAssignment.task_id == Task.id)
                        & (TaskAssignment.company_id == Task.company_id),
                    )
                    .where(TaskAssignment.status == "submitted_for_review")
                )
                rows = (
                    await self._session.execute(
                        statement.order_by(
                            Task.updated_at.desc(), Task.id, TaskAssignment.id
                        )
                    )
                ).all()
                return [await self._task(task, assignment) for task, assignment in rows]
            rows = (
                await self._session.execute(
                    statement.order_by(Task.updated_at.desc(), Task.id)
                )
            ).scalars()
        else:
            raise OrganizationWorkflowInvalid("task view is invalid")
        unique: dict[UUID, Task] = {row.id: row for row in rows}
        return [await self._task(row) for row in unique.values()]

    async def list_task_assignees(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        venue_id: UUID,
        now: datetime,
    ) -> list[dict[str, object]]:
        checked_now = self._aware(now, "now")
        await self._require_venue_capability(
            actor_account_id, company_id, venue_id, "task.manage", checked_now
        )
        rows = (
            await self._session.execute(
                select(EmployeeProfile, Position)
                .join(
                    EmployeeAssignment,
                    (EmployeeAssignment.employee_profile_id == EmployeeProfile.id)
                    & (EmployeeAssignment.company_id == EmployeeProfile.company_id),
                )
                .join(
                    AssignmentVenue,
                    (AssignmentVenue.assignment_id == EmployeeAssignment.id)
                    & (AssignmentVenue.company_id == EmployeeAssignment.company_id),
                )
                .join(
                    Position,
                    (Position.id == EmployeeAssignment.position_id)
                    & (Position.company_id == EmployeeAssignment.company_id),
                )
                .where(
                    EmployeeProfile.company_id == company_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeAssignment.status == "active",
                    EmployeeAssignment.is_primary.is_(True),
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.starts_at <= checked_now,
                    (EmployeeAssignment.ends_at.is_(None))
                    | (EmployeeAssignment.ends_at > checked_now),
                    AssignmentVenue.venue_id == venue_id,
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                )
                .order_by(EmployeeProfile.full_name, EmployeeProfile.id)
            )
        ).all()
        return [
            {
                "employee_profile_id": profile.id,
                "display_name": profile.full_name,
                "position_name": position.name,
            }
            for profile, position in rows
        ]

    async def task_history(
        self,
        actor_account_id: UUID,
        company_id: UUID,
        task_id: UUID,
        now: datetime,
    ) -> list[dict[str, object]]:
        checked_now = self._aware(now, "now")
        task = await self._task_by_id(company_id, task_id, lock=False)
        assigned = (
            await self._session.execute(
                select(TaskAssignment.id)
                .join(
                    EmployeeProfile,
                    (EmployeeProfile.id == TaskAssignment.employee_profile_id)
                    & (EmployeeProfile.company_id == TaskAssignment.company_id),
                )
                .where(
                    TaskAssignment.task_id == task.id,
                    TaskAssignment.company_id == company_id,
                    EmployeeProfile.account_id == actor_account_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if assigned is None and not await self._access.can_for_venue(
            actor_account_id,
            company_id,
            "task.read",
            task.venue_id,
            checked_now,
        ):
            raise OrganizationWorkflowNotFound("task history is unavailable")
        events = (
            await self._session.execute(
                select(TaskEvent)
                .where(
                    TaskEvent.task_id == task.id,
                    TaskEvent.company_id == company_id,
                )
                .order_by(TaskEvent.created_at, TaskEvent.id)
            )
        ).scalars()
        return [
            {"event_type": event.event_type, "occurred_at": event.created_at}
            for event in events
        ]

    async def update_task_draft(self, command: UpdateTaskDraft) -> dict[str, object]:
        now = self._aware(command.now, "now")
        title = self._text(command.title, "title", 255)
        description = self._optional_text(command.description, "description", 4000)
        task = await self._task_by_id(command.company_id, command.task_id, lock=True)
        await self._require_task_manager(command.actor_account_id, task, now)
        if task.status != "draft" or task.version != command.expected_version:
            raise OrganizationWorkflowConflict("task revision is stale")
        task.title = title
        task.description = description
        task.version += 1
        task.updated_at = now
        await self._session.flush()
        await self._event(task, command.actor_account_id, "task_updated", {}, now)
        return await self._task(task)

    async def cancel_task(self, command: CancelTask) -> dict[str, object]:
        now = self._aware(command.now, "now")
        task = await self._task_by_id(command.company_id, command.task_id, lock=True)
        await self._require_task_manager(command.actor_account_id, task, now)
        if task.status == "cancelled":
            return await self._task(task)
        if task.status == "completed" or task.version != command.expected_version:
            raise OrganizationWorkflowConflict("task revision is stale")
        task.status = "cancelled"
        task.version += 1
        task.updated_at = now
        await self._session.flush()
        await self._event(task, command.actor_account_id, "task_cancelled", {}, now)
        return await self._task(task)

    async def dispatch_task(self, command: DispatchTask) -> dict[str, object]:
        now = self._aware(command.now, "now")
        task = await self._task_by_id(command.company_id, command.task_id, lock=True)
        await self._require_task_manager(command.actor_account_id, task, now)
        employee_ids = tuple(sorted(set(command.employee_profile_ids), key=str))
        if not employee_ids or len(employee_ids) > 100:
            raise OrganizationWorkflowInvalid("task assignees are invalid")
        existing_ids = tuple(
            sorted(
                (
                    await self._session.execute(
                        select(TaskAssignment.employee_profile_id).where(
                            TaskAssignment.task_id == task.id,
                            TaskAssignment.company_id == task.company_id,
                        )
                    )
                ).scalars(),
                key=str,
            )
        )
        if task.status == "assigned":
            if existing_ids != employee_ids:
                raise OrganizationWorkflowConflict("task dispatch is unavailable")
            return await self._task(task)
        if task.status != "draft" or task.version != command.expected_version:
            raise OrganizationWorkflowConflict("task revision is stale")
        profiles = (
            await self._session.execute(
                select(EmployeeProfile.id)
                .join(
                    EmployeeAssignment,
                    (EmployeeAssignment.employee_profile_id == EmployeeProfile.id)
                    & (EmployeeAssignment.company_id == EmployeeProfile.company_id),
                )
                .join(
                    AssignmentVenue,
                    (AssignmentVenue.assignment_id == EmployeeAssignment.id)
                    & (AssignmentVenue.company_id == EmployeeAssignment.company_id),
                )
                .where(
                    EmployeeProfile.id.in_(employee_ids),
                    EmployeeProfile.company_id == task.company_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                    EmployeeAssignment.status == "active",
                    EmployeeAssignment.deleted_at.is_(None),
                    EmployeeAssignment.starts_at <= now,
                    (EmployeeAssignment.ends_at.is_(None))
                    | (EmployeeAssignment.ends_at > now),
                    AssignmentVenue.venue_id == task.venue_id,
                )
            )
        ).scalars()
        if set(profiles) != set(employee_ids):
            raise OrganizationWorkflowNotFound("task assignee is unavailable")
        for employee_id in employee_ids:
            self._session.add(
                TaskAssignment(
                    id=uuid5(_NAMESPACE, f"task-assignment-v1:{task.id}:{employee_id}"),
                    task_id=task.id,
                    company_id=task.company_id,
                    employee_profile_id=employee_id,
                    status="assigned",
                    version=1,
                    submitted_at=None,
                    reviewed_at=None,
                    reviewed_by_account_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        task.status = "assigned"
        task.version += 1
        task.dispatched_at = now
        task.updated_at = now
        await self._session.flush()
        await self._event(
            task,
            command.actor_account_id,
            "task_dispatched",
            {"assignee_count": len(employee_ids)},
            now,
        )
        return await self._task(task)

    async def transition_task_assignment(
        self, command: TransitionTaskAssignment
    ) -> dict[str, object]:
        now = self._aware(command.now, "now")
        row = (
            await self._session.execute(
                select(TaskAssignment, Task)
                .join(
                    Task,
                    (Task.id == TaskAssignment.task_id)
                    & (Task.company_id == TaskAssignment.company_id),
                )
                .where(
                    TaskAssignment.id == command.task_assignment_id,
                    TaskAssignment.company_id == command.company_id,
                )
                .with_for_update(of=TaskAssignment)
            )
        ).one_or_none()
        if row is None:
            raise OrganizationWorkflowNotFound("task assignment is unavailable")
        assignment, task = row
        target = {
            "submit": "submitted_for_review",
            "request_changes": "changes_requested",
            "accept": "accepted",
        }.get(command.action)
        if target is None:
            raise OrganizationWorkflowInvalid("task action is invalid")
        if command.action == "submit":
            await self._require_assignment_employee(
                command.actor_account_id, assignment
            )
        else:
            await self._require_task_reviewer(command.actor_account_id, task, now)
        if assignment.status == target:
            return await self._task_assignment(assignment, task)
        if assignment.version != command.expected_version:
            raise OrganizationWorkflowConflict("task assignment revision is stale")
        if command.action == "submit":
            if assignment.status not in {"assigned", "changes_requested"}:
                raise OrganizationWorkflowConflict("task transition is unavailable")
            ready_photo = (
                await self._session.execute(
                    select(TaskPhoto.id).where(
                        TaskPhoto.task_assignment_id == assignment.id,
                        TaskPhoto.task_id == task.id,
                        TaskPhoto.company_id == task.company_id,
                        TaskPhoto.media_status == "ready",
                    )
                )
            ).scalar_one_or_none()
            if ready_photo is None:
                raise OrganizationWorkflowInvalid("completion photo is required")
            assignment.submitted_at = now
            assignment.reviewed_at = None
            assignment.reviewed_by_account_id = None
        else:
            if assignment.status != "submitted_for_review":
                raise OrganizationWorkflowConflict("task transition is unavailable")
            assignment.reviewed_at = now
            assignment.reviewed_by_account_id = command.actor_account_id
        assignment.status = target
        assignment.version += 1
        assignment.updated_at = now
        await self._session.flush()
        await self._event(
            task,
            command.actor_account_id,
            f"assignment_{target}",
            {},
            now,
            discriminator=f"{assignment.id}:{assignment.version}",
        )
        if target == "accepted":
            statuses = set(
                (
                    await self._session.execute(
                        select(TaskAssignment.status).where(
                            TaskAssignment.task_id == task.id,
                            TaskAssignment.company_id == task.company_id,
                        )
                    )
                ).scalars()
            )
            if statuses == {"accepted"}:
                task.status = "completed"
                task.completed_at = now
                task.version += 1
                task.updated_at = now
                await self._event(
                    task, command.actor_account_id, "task_completed", {}, now
                )
        return await self._task_assignment(assignment, task)

    async def _require_company_capability(
        self, account_id: UUID, company_id: UUID, permission: str, now: datetime
    ) -> None:
        if not await self._access.can_in_company(
            account_id, company_id, permission, now
        ):
            raise OrganizationWorkflowNotFound("organization resource is unavailable")

    async def _require_venue_capability(
        self,
        account_id: UUID,
        company_id: UUID,
        venue_id: UUID,
        permission: str,
        now: datetime,
    ) -> None:
        if not await self._access.can_for_venue(
            account_id, company_id, permission, venue_id, now
        ):
            raise OrganizationWorkflowNotFound("organization resource is unavailable")

    async def _require_employee_capability(
        self,
        account_id: UUID,
        company_id: UUID,
        employee_profile_id: UUID,
        permission: str,
        now: datetime,
    ) -> None:
        if await self._access.can_for_employee(
            account_id,
            company_id,
            permission,
            employee_profile_id,
            now,
        ):
            return
        pending_venue_id = (
            await self._session.execute(
                select(GroupInvitation.venue_id)
                .join(
                    GroupInvitationRegistration,
                    (
                        GroupInvitationRegistration.group_invitation_id
                        == GroupInvitation.id
                    )
                    & (
                        GroupInvitationRegistration.company_id
                        == GroupInvitation.company_id
                    ),
                )
                .where(
                    GroupInvitationRegistration.company_id == company_id,
                    GroupInvitationRegistration.employee_profile_id
                    == employee_profile_id,
                    GroupInvitationRegistration.status == "pending_activation",
                )
            )
        ).scalar_one_or_none()
        if pending_venue_id is not None and await self._access.can_for_venue(
            account_id,
            company_id,
            permission,
            pending_venue_id,
            now,
        ):
            return
        raise OrganizationWorkflowNotFound("employee profile is unavailable")

    async def _require_birth_date_access(
        self,
        account_id: UUID,
        profile: EmployeeProfile,
        manager_permission: str,
        now: datetime,
    ) -> bool:
        """Allow the profile owner or a manager whose employee scope covers it."""
        if profile.account_id == account_id:
            return True
        await self._require_employee_capability(
            account_id,
            profile.company_id,
            profile.id,
            manager_permission,
            now,
        )
        return False

    async def _require_task_manager(
        self, account_id: UUID, task: Task, now: datetime
    ) -> None:
        if task.author_account_id == account_id:
            return
        await self._require_venue_capability(
            account_id, task.company_id, task.venue_id, "task.manage", now
        )

    async def _require_task_reviewer(
        self, account_id: UUID, task: Task, now: datetime
    ) -> None:
        if task.author_account_id == account_id:
            return
        await self._require_venue_capability(
            account_id, task.company_id, task.venue_id, "task.review", now
        )

    async def _require_assignment_employee(
        self, account_id: UUID, assignment: TaskAssignment
    ) -> None:
        exists = (
            await self._session.execute(
                select(EmployeeProfile.id).where(
                    EmployeeProfile.id == assignment.employee_profile_id,
                    EmployeeProfile.company_id == assignment.company_id,
                    EmployeeProfile.account_id == account_id,
                    EmployeeProfile.employment_status == "active",
                    EmployeeProfile.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if exists is None:
            raise OrganizationWorkflowNotFound("task assignment is unavailable")

    async def _available_position(
        self, company_id: UUID, position_id: UUID
    ) -> tuple[Position, AccessProfile]:
        row = (
            await self._session.execute(
                select(Position, AccessProfile)
                .join(
                    AccessProfile,
                    (AccessProfile.id == Position.default_access_profile_id)
                    & (AccessProfile.company_id == Position.company_id),
                )
                .where(
                    Position.id == position_id,
                    Position.company_id == company_id,
                    Position.is_active.is_(True),
                    Position.deleted_at.is_(None),
                    AccessProfile.is_active.is_(True),
                    AccessProfile.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise OrganizationWorkflowNotFound("position is unavailable")
        return row

    async def _birth_date_profile(
        self, company_id: UUID, employee_profile_id: UUID, *, lock: bool
    ) -> EmployeeProfile:
        statement = select(EmployeeProfile).where(
            EmployeeProfile.id == employee_profile_id,
            EmployeeProfile.company_id == company_id,
            EmployeeProfile.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        profile = (await self._session.execute(statement)).scalar_one_or_none()
        if profile is None:
            raise OrganizationWorkflowNotFound("employee profile is unavailable")
        return profile

    async def _invitation_by_id(
        self, company_id: UUID, invitation_id: UUID, *, lock: bool
    ) -> GroupInvitation:
        statement = select(GroupInvitation).where(
            GroupInvitation.id == invitation_id,
            GroupInvitation.company_id == company_id,
        )
        if lock:
            statement = statement.with_for_update()
        invitation = (await self._session.execute(statement)).scalar_one_or_none()
        if invitation is None:
            raise OrganizationWorkflowNotFound("invitation is unavailable")
        return invitation

    async def _task_by_id(self, company_id: UUID, task_id: UUID, *, lock: bool) -> Task:
        statement = select(Task).where(
            Task.id == task_id, Task.company_id == company_id
        )
        if lock:
            statement = statement.with_for_update()
        task = (await self._session.execute(statement)).scalar_one_or_none()
        if task is None:
            raise OrganizationWorkflowNotFound("task is unavailable")
        return task

    async def _event(
        self,
        task: Task,
        actor_account_id: UUID,
        event_type: str,
        metadata: dict[str, object],
        now: datetime,
        *,
        discriminator: str = "task",
    ) -> None:
        self._session.add(
            TaskEvent(
                id=uuid5(
                    _NAMESPACE,
                    f"task-event-v1:{task.id}:{task.version}:{event_type}:"
                    f"{discriminator}",
                ),
                task_id=task.id,
                company_id=task.company_id,
                actor_account_id=actor_account_id,
                event_type=event_type,
                safe_metadata=metadata,
                created_at=now,
            )
        )
        await self._session.flush()

    async def _task(
        self, task: Task, assignment: TaskAssignment | None = None
    ) -> dict[str, object]:
        assignments = (
            await self._session.execute(
                select(TaskAssignment).where(
                    TaskAssignment.task_id == task.id,
                    TaskAssignment.company_id == task.company_id,
                )
            )
        ).scalars()
        photo_statement = select(func.count(TaskPhoto.id)).where(
            TaskPhoto.task_id == task.id,
            TaskPhoto.company_id == task.company_id,
            TaskPhoto.media_status == "ready",
        )
        if assignment is not None:
            photo_statement = photo_statement.where(
                TaskPhoto.task_assignment_id == assignment.id
            )
        photo_count = (await self._session.execute(photo_statement)).scalar_one()
        return {
            "task_id": task.id,
            "company_id": task.company_id,
            "venue_id": task.venue_id,
            "assessment_attempt_id": task.assessment_attempt_id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "version": task.version,
            "assignment_count": len(list(assignments)),
            "task_assignment_id": assignment.id if assignment is not None else None,
            "assignment_status": assignment.status if assignment is not None else None,
            "assignment_version": (
                assignment.version if assignment is not None else None
            ),
            "photo_count": photo_count,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    async def _task_assignment(
        self, assignment: TaskAssignment, task: Task
    ) -> dict[str, object]:
        photo_count = (
            await self._session.execute(
                select(func.count(TaskPhoto.id)).where(
                    TaskPhoto.task_assignment_id == assignment.id,
                    TaskPhoto.task_id == task.id,
                    TaskPhoto.company_id == task.company_id,
                    TaskPhoto.media_status == "ready",
                )
            )
        ).scalar_one()
        return {
            "task_assignment_id": assignment.id,
            "task_id": task.id,
            "task_status": task.status,
            "status": assignment.status,
            "version": assignment.version,
            "submitted_at": assignment.submitted_at,
            "reviewed_at": assignment.reviewed_at,
            "photo_count": photo_count,
        }

    @staticmethod
    def _position(position: Position, profile: AccessProfile) -> dict[str, object]:
        preset = OrganizationWorkflowService._preset_for_access(
            profile, position.default_scope_type
        )
        return {
            "position_id": position.id,
            "name": position.name,
            "description": position.description,
            "sort_order": position.sort_order,
            "access_preset": preset,
            "revision": position.updated_at,
        }

    @staticmethod
    def _preset_for_access(
        profile: AccessProfile, default_scope_type: str | None
    ) -> str:
        mapping = {
            ("owner", "company"): "owner",
            ("owner", None): "owner",
            ("employee", "self"): "employee_unassigned",
            ("employee", "working_venues"): "employee_venue",
            ("venue-manager", "explicit_venues"): "venue_manager",
            ("organization-manager", "company"): "organization_manager",
        }
        preset = mapping.get((profile.code, default_scope_type))
        if preset is None:
            raise OrganizationWorkflowConflict("access profile is incompatible")
        return preset

    @staticmethod
    def _registration(
        registration: GroupInvitationRegistration,
        profile: EmployeeProfile,
        invitation: GroupInvitation,
    ) -> dict[str, object]:
        return {
            "registration_id": registration.id,
            "company_id": registration.company_id,
            "venue_id": invitation.venue_id,
            "employee_profile_id": profile.id,
            "display_name": profile.full_name,
            "status": registration.status,
            "created_at": registration.created_at,
            "activated_at": registration.activated_at,
        }

    @staticmethod
    def _birth_date_projection(profile: EmployeeProfile) -> dict[str, object]:
        return {
            "employee_profile_id": profile.id,
            "birth_date": profile.birth_date,
            "revision": profile.updated_at,
        }

    @staticmethod
    def _group_invitation(
        invitation: GroupInvitation, token: str | None
    ) -> dict[str, object]:
        return {
            "invitation_id": invitation.id,
            "company_id": invitation.company_id,
            "venue_id": invitation.venue_id,
            "position_id": invitation.position_id,
            "label": invitation.label,
            "status": invitation.status,
            "max_registrations": invitation.max_registrations,
            "registration_count": invitation.registration_count,
            "expires_at": invitation.expires_at,
            "join_path": f"/join-group#token={token}" if token is not None else None,
        }

    def _same_invitation(
        self,
        invitation: GroupInvitation,
        command: CreateGroupInvitation,
        position: Position,
        access_profile: AccessProfile,
        label: str,
        expires_at: datetime,
        digest: bytes,
    ) -> None:
        if (
            invitation.company_id != command.company_id
            or invitation.venue_id != command.venue_id
            or invitation.position_id != position.id
            or invitation.access_profile_id != access_profile.id
            or invitation.created_by_account_id != command.actor_account_id
            or invitation.label != label
            or invitation.expires_at != expires_at
            or invitation.max_registrations != command.max_registrations
            or not hmac.compare_digest(invitation.token_digest, digest)
        ):
            raise OrganizationWorkflowConflict("invitation request is unavailable")

    def _invitation_token(self, company_id: UUID, request_id: UUID) -> str:
        digest = hmac.new(
            self._invitation_pepper,
            f"group-invitation-token-v1:{company_id}:{request_id}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def _invitation_digest(self, token: str) -> bytes:
        return hmac.new(
            self._invitation_pepper,
            b"group-invitation-digest-v1:" + token.encode("ascii"),
            hashlib.sha256,
        ).digest()

    @staticmethod
    def _token(value: str) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 43
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value)
        ):
            raise OrganizationWorkflowNotFound("group invitation is unavailable")
        return value

    @staticmethod
    def _text(value: str | None, name: str, maximum: int) -> str:
        if not isinstance(value, str):
            raise OrganizationWorkflowInvalid(f"{name} is invalid")
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > maximum:
            raise OrganizationWorkflowInvalid(f"{name} is invalid")
        return normalized

    @staticmethod
    def _birth_date(value: date, now: datetime) -> date:
        if (
            not isinstance(value, date)
            or isinstance(value, datetime)
            or value < date(1900, 1, 1)
            or value >= now.date()
        ):
            raise OrganizationWorkflowInvalid("birth_date is invalid")
        return value

    @classmethod
    def _optional_text(cls, value: str | None, name: str, maximum: int) -> str | None:
        return (
            None
            if value is None or not value.strip()
            else cls._text(value, name, maximum)
        )

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise OrganizationWorkflowInvalid(f"{name} must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _slug(value: str) -> str:
        slug = _CODE_PARTS.sub(
            "-", value.casefold().encode("ascii", "ignore").decode()
        ).strip("-")
        return slug or "position"
