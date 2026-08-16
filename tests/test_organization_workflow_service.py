"""PostgreSQL regressions for organization onboarding and task workflows."""

import base64
import asyncio
from datetime import date, datetime, timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infra.database.models.employee_assignment import EmployeeAssignment
from app.infra.database.models.employee_profile import (
    EmployeeBirthDateAudit,
    EmployeeProfile,
)
from app.infra.database.models.organization_workflow import (
    GroupInvitation,
    Task,
    TaskAssignment,
    TaskEvent,
    TaskPhoto,
)
from app.infra.media import S3PrivateMediaStore, S3PrivateMediaStoreSettings
from app.internal.services.account_legal_contract import (
    AUTH_SMS_CONSENT_VERSION,
    DOCUMENT_SET_VERSION,
    PD_CONSENT_VERSION,
    PRIVACY_VERSION,
    REGISTRATION_OTP_MESSAGE_TYPE,
    TERMS_VERSION,
    AccountRegistrationAcceptance,
    RegistrationSmsConsent,
)
from app.internal.services.account_session_service import AccountSessionService
from app.internal.services.account_organization_access_service import (
    AccountOrganizationAccessService,
    CreateOrganizationVenue,
    ReplaceEmployeeAccess,
)
from app.internal.services.device_registration_challenge_service import (
    DeviceRegistrationChallengeService,
    IssueAccountDeviceRegistrationChallenge,
    canonical_account_registration_message,
)
from app.internal.services.first_company_service import (
    CreateFirstCompany,
    FirstCompanyService,
)
from app.internal.services.organization_workflow_service import (
    ActivateGroupRegistration,
    CancelTask,
    CreateGroupInvitation,
    CreatePosition,
    CreateTaskDraft,
    DispatchTask,
    JoinGroupInvitation,
    OrganizationWorkflowInvalid,
    OrganizationWorkflowConflict,
    OrganizationWorkflowNotFound,
    OrganizationWorkflowService,
    OrganizationWorkflowUnavailable,
    TransitionTaskAssignment,
    UpdateEmployeeBirthDate,
    UpdateTaskDraft,
)
from app.internal.services.phone_verification_service import (
    PhoneVerificationService,
    RequestPhoneVerificationCode,
    VerifyPhoneVerificationCode,
)
from app.internal.services.standalone_account_auth_service import (
    RegisterStandaloneAccount,
    StandaloneAccountAuthService,
)
from app.internal.services.task_media_service import (
    ReserveTaskPhoto,
    TaskMediaService,
    sanitize_image,
)


NOW = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
PHONE_PEPPER = b"organization-workflow-phone-pepper"
CODE_PEPPER = b"organization-workflow-code-pepper-32"
SESSION_PEPPER = b"organization-workflow-session-pepper"
AUTH_INVITATION_PEPPER = b"organization-workflow-auth-invite"
GROUP_PEPPER = b"organization-group-invitation-pepper-v1"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMA"
    "ASsJTYQAAAAASUVORK5CYII="
)


class ControlledSmsSender:
    def __init__(self):
        self.messages: list[dict[str, object]] = []

    async def send_verification_code(self, **message):
        self.messages.append(message)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    connection = await engine.connect()
    transaction = await connection.begin()
    value = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield value
    finally:
        await value.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


async def register_account(session: AsyncSession, label: str):
    phone = f"+7998{uuid4().int % 10_000_000:07d}"
    sender = ControlledSmsSender()
    verification = PhoneVerificationService(
        session, sender, PHONE_PEPPER, CODE_PEPPER, "pilot.restos.space"
    )
    requested = await verification.request_code(
        RequestPhoneVerificationCode(
            purpose="account_registration",
            phone=phone,
            registration_sms_consent=RegistrationSmsConsent(
                personal_data_consent=True,
                personal_data_consent_version=PD_CONSENT_VERSION,
                authorization_sms_consent=True,
                authorization_sms_consent_version=AUTH_SMS_CONSENT_VERSION,
            ),
            auth_sms_message_type=REGISTRATION_OTP_MESSAGE_TYPE,
            now=NOW,
        )
    )
    code = sender.messages[-1]["code"]
    assert isinstance(code, str)
    await verification.verify_code(
        VerifyPhoneVerificationCode(
            challenge_id=requested.challenge_id,
            phone=phone,
            code=code,
            now=NOW + timedelta(milliseconds=100),
        )
    )
    device_service = DeviceRegistrationChallengeService(
        session, AUTH_INVITATION_PEPPER, PHONE_PEPPER
    )
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    app_instance_id = uuid4()
    device = await device_service.issue_account_registration_challenge(
        IssueAccountDeviceRegistrationChallenge(
            phone_verification_challenge_id=requested.challenge_id,
            phone=phone,
            app_instance_id=app_instance_id,
            platform="web",
            public_key=public_key,
            now=NOW + timedelta(milliseconds=200),
        )
    )
    nonce = base64.urlsafe_b64decode(device.nonce + "=")
    signature = private_key.sign(
        canonical_account_registration_message(
            device_challenge_id=device.device_challenge_id,
            phone_challenge_id=requested.challenge_id,
            app_instance_id=app_instance_id,
            platform="web",
            nonce=nonce,
        ),
        ec.ECDSA(hashes.SHA256()),
    )
    registered = await StandaloneAccountAuthService(
        session,
        AccountSessionService(session, SESSION_PEPPER),
        device_service,
        PHONE_PEPPER,
    ).register(
        RegisterStandaloneAccount(
            phone_verification_challenge_id=requested.challenge_id,
            phone=phone,
            display_name=label,
            password="correct horse battery",
            app_instance_id=app_instance_id,
            platform="web",
            device_display_name="Synthetic Browser",
            device_challenge_id=device.device_challenge_id,
            device_challenge_nonce=nonce,
            device_challenge_signature=signature,
            legal_acceptance=AccountRegistrationAcceptance(
                document_set_version=DOCUMENT_SET_VERSION,
                terms_version=TERMS_VERSION,
                privacy_version=PRIVACY_VERSION,
            ),
            now=NOW + timedelta(milliseconds=300),
        )
    )
    return SimpleNamespace(id=registered.account_id, phone=phone)


async def create_company(session: AsyncSession, label: str):
    owner = await register_account(session, f"{label} Owner")
    company = await FirstCompanyService(session).create(
        CreateFirstCompany(
            account_id=owner.id,
            expected_security_version=1,
            company_name=f"{label} {uuid4().hex[:8]}",
            venue_name=f"{label} Venue",
            timezone="Europe/Moscow",
            locale="ru-RU",
            now=NOW + timedelta(seconds=1),
        )
    )
    return owner, company


async def create_position_and_invitation(
    session: AsyncSession, owner, company, *, capacity: int = 2
):
    service = OrganizationWorkflowService(session, invitation_pepper=GROUP_PEPPER)
    position = await service.create_position(
        CreatePosition(
            owner.id,
            company.company_id,
            uuid4(),
            "Официант",
            "Работа с гостями",
            "employee_venue",
            10,
            NOW + timedelta(seconds=2),
        )
    )
    invitation = await service.create_group_invitation(
        CreateGroupInvitation(
            owner.id,
            company.company_id,
            uuid4(),
            company.venue_id,
            position["position_id"],
            "Новая команда",
            NOW + timedelta(days=7),
            capacity,
            NOW + timedelta(seconds=3),
        )
    )
    join_path = invitation["join_path"]
    assert isinstance(join_path, str)
    return service, position, invitation, join_path.split("#token=", 1)[1]


async def join_and_activate(session, service, owner, company, token, label):
    account = await register_account(session, label)
    registration = await service.join_group_invitation(
        JoinGroupInvitation(
            account.id,
            token,
            uuid4(),
            label,
            "Сотрудник",
            date(1995, 4, 12),
            NOW + timedelta(seconds=4),
        )
    )
    activated = await service.activate_group_registration(
        ActivateGroupRegistration(
            owner.id,
            company.company_id,
            registration["registration_id"],
            NOW + timedelta(seconds=5),
        )
    )
    return account, activated


@pytest.mark.asyncio
async def test_position_group_join_pending_activation_and_revoke(session):
    owner, company = await create_company(session, "Alpha")
    service, position, invitation, token = await create_position_and_invitation(
        session, owner, company, capacity=1
    )
    positions = await service.list_positions(
        owner.id, company.company_id, NOW + timedelta(seconds=3)
    )
    assert [item["access_preset"] for item in positions] == ["owner", "employee_venue"]
    stored = await session.get(GroupInvitation, invitation["invitation_id"])
    repeated = await service.create_group_invitation(
        CreateGroupInvitation(
            owner.id,
            company.company_id,
            stored.request_id,
            company.venue_id,
            position["position_id"],
            "Новая команда",
            NOW + timedelta(days=7),
            1,
            NOW + timedelta(seconds=3),
        )
    )
    assert repeated["join_path"] == invitation["join_path"]
    assert token.encode("ascii") not in stored.token_digest
    account = await register_account(session, "Анна")
    joined = await service.join_group_invitation(
        JoinGroupInvitation(
            account.id,
            token,
            uuid4(),
            "Анна",
            "Сотрудник",
            date(1994, 2, 3),
            NOW + timedelta(seconds=4),
        )
    )
    profile = await session.get(EmployeeProfile, joined["employee_profile_id"])
    assert joined["status"] == "pending_activation"
    assert profile.birth_date == date(1994, 2, 3)
    assert profile.employment_status == "pending_activation"
    assert (
        await session.scalar(
            select(func.count())
            .select_from(EmployeeAssignment)
            .where(EmployeeAssignment.employee_profile_id == profile.id)
        )
        == 0
    )
    activated = await service.activate_group_registration(
        ActivateGroupRegistration(
            owner.id,
            company.company_id,
            joined["registration_id"],
            NOW + timedelta(seconds=5),
        )
    )
    repeated_activation = await service.activate_group_registration(
        ActivateGroupRegistration(
            owner.id,
            company.company_id,
            joined["registration_id"],
            NOW + timedelta(seconds=6),
        )
    )
    assert activated["status"] == repeated_activation["status"] == "active"
    assert (
        await session.scalar(
            select(func.count())
            .select_from(EmployeeAssignment)
            .where(EmployeeAssignment.employee_profile_id == profile.id)
        )
        == 1
    )
    revoked = await service.revoke_group_invitation(
        owner.id,
        company.company_id,
        invitation["invitation_id"],
        NOW + timedelta(seconds=7),
    )
    assert revoked["status"] == "revoked" and revoked["join_path"] is None
    outsider = await register_account(session, "Лишний")
    with pytest.raises(OrganizationWorkflowNotFound):
        await service.join_group_invitation(
            JoinGroupInvitation(
                outsider.id,
                token,
                uuid4(),
                "Лишний",
                "Сотрудник",
                date(1990, 1, 1),
                NOW + timedelta(seconds=8),
            )
        )
    assert await session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_birth_date_is_scoped_strict_and_append_only_audited(session):
    owner, company = await create_company(session, "DOB scope")
    workflow, _, _, token = await create_position_and_invitation(
        session, owner, company, capacity=4
    )
    employee, target = await join_and_activate(
        session, workflow, owner, company, token, "Target employee"
    )
    manager, manager_membership = await join_and_activate(
        session, workflow, owner, company, token, "Venue manager"
    )
    access = AccountOrganizationAccessService(session)
    current_manager = await access.employee_access(
        owner.id,
        company.company_id,
        manager_membership["employee_profile_id"],
        NOW + timedelta(seconds=7),
    )
    await access.replace_employee_access(
        ReplaceEmployeeAccess(
            owner.id,
            company.company_id,
            manager_membership["employee_profile_id"],
            "venue_manager",
            (company.venue_id,),
            current_manager["revision"],
            NOW + timedelta(seconds=8),
        )
    )

    protected = await workflow.employee_birth_date(
        manager.id,
        company.company_id,
        target["employee_profile_id"],
        NOW + timedelta(seconds=9),
    )
    assert protected["birth_date"] == date(1995, 4, 12)
    own = await workflow.employee_birth_date(
        employee.id,
        company.company_id,
        target["employee_profile_id"],
        NOW + timedelta(seconds=9),
    )
    assert own["birth_date"] == date(1995, 4, 12)
    with pytest.raises(OrganizationWorkflowNotFound):
        await workflow.employee_birth_date(
            employee.id,
            company.company_id,
            manager_membership["employee_profile_id"],
            NOW + timedelta(seconds=9),
        )

    self_updated = await workflow.update_employee_birth_date(
        UpdateEmployeeBirthDate(
            employee.id,
            company.company_id,
            target["employee_profile_id"],
            date(1995, 4, 12),
            date(1995, 4, 13),
            NOW + timedelta(seconds=10),
        )
    )
    assert self_updated["birth_date"] == date(1995, 4, 13)
    own_audit = await workflow.employee_birth_date_audit(
        employee.id,
        company.company_id,
        target["employee_profile_id"],
        NOW + timedelta(seconds=11),
    )
    assert [row["source"] for row in own_audit] == [
        "group_onboarding",
        "employee_update",
    ]
    assert own_audit[1]["actor_account_id"] == employee.id

    updated = await workflow.update_employee_birth_date(
        UpdateEmployeeBirthDate(
            manager.id,
            company.company_id,
            target["employee_profile_id"],
            date(1995, 4, 13),
            date(1995, 4, 14),
            NOW + timedelta(seconds=12),
        )
    )
    assert updated["birth_date"] == date(1995, 4, 14)
    audit = await workflow.employee_birth_date_audit(
        owner.id,
        company.company_id,
        target["employee_profile_id"],
        NOW + timedelta(seconds=13),
    )
    assert [row["source"] for row in audit] == [
        "group_onboarding",
        "employee_update",
        "manager_update",
    ]
    assert audit[0]["previous_birth_date"] is None
    assert audit[1]["previous_birth_date"] == date(1995, 4, 12)
    assert audit[1]["birth_date"] == date(1995, 4, 13)
    assert audit[2]["previous_birth_date"] == date(1995, 4, 13)
    assert audit[2]["birth_date"] == date(1995, 4, 14)
    assert audit[2]["actor_account_id"] == manager.id
    assert (
        await session.scalar(
            select(func.count())
            .select_from(EmployeeBirthDateAudit)
            .where(
                EmployeeBirthDateAudit.employee_profile_id
                == target["employee_profile_id"]
            )
        )
        == 3
    )

    with pytest.raises(OrganizationWorkflowConflict):
        await workflow.update_employee_birth_date(
            UpdateEmployeeBirthDate(
                manager.id,
                company.company_id,
                target["employee_profile_id"],
                date(1995, 4, 13),
                date(1995, 4, 15),
                NOW + timedelta(seconds=14),
            )
        )
    with pytest.raises(OrganizationWorkflowInvalid):
        await workflow.update_employee_birth_date(
            UpdateEmployeeBirthDate(
                manager.id,
                company.company_id,
                target["employee_profile_id"],
                date(1995, 4, 14),
                datetime(1995, 4, 15, tzinfo=timezone.utc),  # type: ignore[arg-type]
                NOW + timedelta(seconds=15),
            )
        )

    second = await access.create_venue(
        CreateOrganizationVenue(
            owner.id,
            company.company_id,
            uuid4(),
            "Other venue",
            "Europe/Moscow",
            NOW + timedelta(seconds=16),
        )
    )
    second_invitation = await workflow.create_group_invitation(
        CreateGroupInvitation(
            owner.id,
            company.company_id,
            uuid4(),
            second["venue_id"],
            (
                await workflow.list_positions(
                    owner.id, company.company_id, NOW + timedelta(seconds=17)
                )
            )[-1]["position_id"],
            "Other venue team",
            NOW + timedelta(days=7),
            2,
            NOW + timedelta(seconds=17),
        )
    )
    other_token = second_invitation["join_path"].split("#token=", 1)[1]
    _, other_employee = await join_and_activate(
        session, workflow, owner, company, other_token, "Other employee"
    )
    with pytest.raises(OrganizationWorkflowNotFound):
        await workflow.employee_birth_date(
            manager.id,
            company.company_id,
            other_employee["employee_profile_id"],
            NOW + timedelta(seconds=18),
        )
    foreign_owner, foreign_company = await create_company(session, "Foreign DOB")
    with pytest.raises(OrganizationWorkflowNotFound):
        await workflow.employee_birth_date(
            foreign_owner.id,
            foreign_company.company_id,
            target["employee_profile_id"],
            NOW + timedelta(seconds=19),
        )
    assert await session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_two_assignee_task_closes_only_after_both_accept(session):
    owner, company = await create_company(session, "Tasks")
    service, _, _, token = await create_position_and_invitation(session, owner, company)
    first, first_registration = await join_and_activate(
        session, service, owner, company, token, "Первый"
    )
    second, second_registration = await join_and_activate(
        session, service, owner, company, token, "Второй"
    )
    request_id = uuid4()
    command = CreateTaskDraft(
        owner.id,
        company.company_id,
        company.venue_id,
        request_id,
        None,
        "Проверить холодильник",
        "Приложить фото результата",
        NOW + timedelta(seconds=6),
    )
    draft = await service.create_task_draft(command)
    assert (await service.create_task_draft(command))["task_id"] == draft["task_id"]
    assignees = await service.list_task_assignees(
        owner.id,
        company.company_id,
        company.venue_id,
        NOW + timedelta(seconds=7),
    )
    assert {item["employee_profile_id"] for item in assignees} >= {
        first_registration["employee_profile_id"],
        second_registration["employee_profile_id"],
    }
    assert all(
        set(item) == {"employee_profile_id", "display_name", "position_name"}
        for item in assignees
    )
    dispatched = await service.dispatch_task(
        DispatchTask(
            owner.id,
            company.company_id,
            draft["task_id"],
            (
                first_registration["employee_profile_id"],
                second_registration["employee_profile_id"],
            ),
            1,
            NOW + timedelta(seconds=7),
        )
    )
    assert dispatched["status"] == "assigned"
    mine = await service.list_tasks(
        first.id, company.company_id, "mine", NOW + timedelta(seconds=7)
    )
    assert len(mine) == 1
    assert mine[0]["task_assignment_id"] is not None
    assert mine[0]["assignment_status"] == "assigned"
    assert mine[0]["assignment_version"] == 1
    assignments = list(
        (
            await session.execute(
                select(TaskAssignment)
                .where(TaskAssignment.task_id == draft["task_id"])
                .order_by(TaskAssignment.employee_profile_id)
            )
        ).scalars()
    )
    account_by_profile = {
        first_registration["employee_profile_id"]: first,
        second_registration["employee_profile_id"]: second,
    }
    media = TaskMediaService(session)
    for index, assignment in enumerate(assignments):
        account = account_by_profile[assignment.employee_profile_id]
        reserved = await media.reserve(
            ReserveTaskPhoto(
                account.id,
                company.company_id,
                draft["task_id"],
                assignment.id,
                "image/png",
                PNG,
                NOW + timedelta(seconds=8 + index),
            )
        )
        await media.mark_ready(
            company.company_id,
            reserved.photo_id,
            reserved.digest,
            NOW + timedelta(seconds=10 + index),
        )
        submitted = await service.transition_task_assignment(
            TransitionTaskAssignment(
                account.id,
                company.company_id,
                assignment.id,
                "submit",
                assignment.version,
                NOW + timedelta(seconds=12 + index),
            )
        )
        assert submitted["status"] == "submitted_for_review"
    first_assignment = assignments[0]
    returned = await service.transition_task_assignment(
        TransitionTaskAssignment(
            owner.id,
            company.company_id,
            first_assignment.id,
            "request_changes",
            2,
            NOW + timedelta(seconds=20),
        )
    )
    resubmitted = await service.transition_task_assignment(
        TransitionTaskAssignment(
            account_by_profile[first_assignment.employee_profile_id].id,
            company.company_id,
            first_assignment.id,
            "submit",
            returned["version"],
            NOW + timedelta(seconds=21),
        )
    )
    accepted_first = await service.transition_task_assignment(
        TransitionTaskAssignment(
            owner.id,
            company.company_id,
            first_assignment.id,
            "accept",
            resubmitted["version"],
            NOW + timedelta(seconds=22),
        )
    )
    assert accepted_first["task_status"] == "assigned"
    accepted_second = await service.transition_task_assignment(
        TransitionTaskAssignment(
            owner.id,
            company.company_id,
            assignments[1].id,
            "accept",
            2,
            NOW + timedelta(seconds=23),
        )
    )
    assert accepted_second["task_status"] == "completed"
    assert (
        await session.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.id == draft["task_id"], Task.status == "completed")
        )
        == 1
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(TaskAssignment)
            .where(
                TaskAssignment.task_id == draft["task_id"],
                TaskAssignment.status == "accepted",
            )
        )
        == 2
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(TaskPhoto)
            .where(
                TaskPhoto.task_id == draft["task_id"],
                TaskPhoto.media_status == "ready",
            )
        )
        == 2
    )
    assert (
        await session.scalar(
            select(func.count())
            .select_from(TaskEvent)
            .where(TaskEvent.task_id == draft["task_id"])
        )
        >= 9
    )
    history = await service.task_history(
        owner.id,
        company.company_id,
        draft["task_id"],
        NOW + timedelta(seconds=24),
    )
    assert history[0]["event_type"] == "task_created"
    assert {"assignment_accepted", "task_completed"}.issubset(
        {event["event_type"] for event in history}
    )
    assert all(set(event) == {"event_type", "occurred_at"} for event in history)


@pytest.mark.asyncio
async def test_cross_company_group_invitation_fails_closed(session):
    owner, company = await create_company(session, "Alpha")
    outsider, foreign = await create_company(session, "Foreign")
    _, position, _, _ = await create_position_and_invitation(session, owner, company)
    with pytest.raises(OrganizationWorkflowNotFound):
        await OrganizationWorkflowService(
            session, invitation_pepper=GROUP_PEPPER
        ).create_group_invitation(
            CreateGroupInvitation(
                outsider.id,
                company.company_id,
                uuid4(),
                company.venue_id,
                position["position_id"],
                "Foreign",
                NOW + timedelta(days=7),
                10,
                NOW,
            )
        )
    assert foreign.company_id != company.company_id
    assert await session.scalar(select(1)) == 1


@pytest.mark.asyncio
async def test_task_draft_update_and_cancel_are_revision_safe(session):
    owner, company = await create_company(session, "Task edit")
    service = OrganizationWorkflowService(session, invitation_pepper=GROUP_PEPPER)
    draft = await service.create_task_draft(
        CreateTaskDraft(
            owner.id,
            company.company_id,
            company.venue_id,
            uuid4(),
            None,
            "Проверить зал",
            None,
            NOW + timedelta(seconds=2),
        )
    )
    updated = await service.update_task_draft(
        UpdateTaskDraft(
            owner.id,
            company.company_id,
            draft["task_id"],
            1,
            "Проверить зал и вход",
            "До открытия",
            NOW + timedelta(seconds=3),
        )
    )
    assert updated["version"] == 2
    assert updated["title"] == "Проверить зал и вход"
    cancelled = await service.cancel_task(
        CancelTask(
            owner.id,
            company.company_id,
            draft["task_id"],
            2,
            NOW + timedelta(seconds=4),
        )
    )
    repeated = await service.cancel_task(
        CancelTask(
            owner.id,
            company.company_id,
            draft["task_id"],
            2,
            NOW + timedelta(seconds=5),
        )
    )
    assert cancelled["status"] == repeated["status"] == "cancelled"
    assert cancelled["version"] == repeated["version"] == 3


def test_image_sanitizer_rejects_mime_mismatch():
    sanitized, mime_type, extension = sanitize_image(PNG, "image/png")
    assert mime_type == "image/png" and extension == "png"
    assert b"tEXt" not in sanitized and b"eXIf" not in sanitized
    with pytest.raises(Exception):
        sanitize_image(PNG, "image/jpeg")


def test_public_dtos_hide_birth_date_tokens_and_object_keys():
    from app.api.routers import account_organization_workflows as api

    names = {
        name
        for model in (
            api.GroupRegistrationResponse,
            api.GroupInvitationResponse,
            api.TaskResponse,
            api.TaskAssignmentResponse,
            api.TaskAssigneeResponse,
            api.TaskEventResponse,
            api.TaskPhotoResponse,
        )
        for name in model.model_fields
    }
    assert names.isdisjoint(
        {"birth_date", "token", "token_digest", "object_key", "sha256_digest"}
    )


def test_birth_date_audit_is_profile_owned_and_privacy_deletable():
    profile_foreign_key = next(
        constraint
        for constraint in EmployeeBirthDateAudit.__table__.foreign_key_constraints
        if constraint.name == "fk_employee_birth_date_audits_profile_company"
    )
    assert profile_foreign_key.ondelete == "CASCADE"


def test_group_onboarding_dob_release_gate_and_strict_requests(monkeypatch):
    from fastapi import HTTPException
    from pydantic import ValidationError

    from app.api.routers import account_organization_workflows as api

    monkeypatch.setattr(
        api.config, "ACCOUNT_GROUP_ONBOARDING_DOB_LEGAL_PUBLISHED", False
    )
    with pytest.raises(HTTPException) as blocked:
        api._require_group_onboarding_legal_publication()
    assert blocked.value.status_code == 503
    assert blocked.value.detail == {"code": "group_onboarding_legal_pending"}
    assert blocked.value.headers == {"Cache-Control": "private, no-store"}

    monkeypatch.setattr(
        api.config, "ACCOUNT_GROUP_ONBOARDING_DOB_LEGAL_PUBLISHED", True
    )
    api._require_group_onboarding_legal_publication()
    valid = api.JoinGroupInvitationRequest(
        token="A" * 43,
        request_id=uuid4(),
        first_name="Анна",
        last_name="Сотрудник",
        birth_date="1994-02-03",
    )
    assert valid.birth_date == date(1994, 2, 3)
    for invalid in ("1994-2-3", "1994-02-03T00:00:00Z", 19940203):
        with pytest.raises(ValidationError):
            api.JoinGroupInvitationRequest(
                token="A" * 43,
                request_id=uuid4(),
                first_name="Анна",
                last_name="Сотрудник",
                birth_date=invalid,
            )


def test_openapi_workflow_operations_are_strict_and_typed():
    from app.api.main import create_app

    schema = create_app().openapi()
    expected = {
        ("get", "/api/v1/account/organization/access-presets"),
        ("get", "/api/v1/account/task-media/capability"),
        ("get", "/api/v1/account/companies/{company_id}/organization/positions"),
        ("post", "/api/v1/account/companies/{company_id}/organization/positions"),
        (
            "get",
            "/api/v1/account/companies/{company_id}/organization/group-invitations",
        ),
        (
            "post",
            "/api/v1/account/companies/{company_id}/organization/group-invitations",
        ),
        (
            "delete",
            "/api/v1/account/companies/{company_id}/organization/group-invitations/{invitation_id}",
        ),
        ("post", "/api/v1/account/organization/group-invitations/join"),
        (
            "get",
            "/api/v1/account/companies/{company_id}/organization/employees/{employee_profile_id}/birth-date",
        ),
        (
            "put",
            "/api/v1/account/companies/{company_id}/organization/employees/{employee_profile_id}/birth-date",
        ),
        (
            "get",
            "/api/v1/account/companies/{company_id}/organization/employees/{employee_profile_id}/birth-date/audit",
        ),
        (
            "get",
            "/api/v1/account/companies/{company_id}/organization/pending-registrations",
        ),
        (
            "post",
            "/api/v1/account/companies/{company_id}/organization/pending-registrations/{registration_id}/activate",
        ),
        ("get", "/api/v1/account/companies/{company_id}/tasks"),
        ("get", "/api/v1/account/companies/{company_id}/tasks/assignees"),
        ("get", "/api/v1/account/companies/{company_id}/tasks/{task_id}/history"),
        ("post", "/api/v1/account/companies/{company_id}/tasks"),
        ("put", "/api/v1/account/companies/{company_id}/tasks/{task_id}"),
        ("delete", "/api/v1/account/companies/{company_id}/tasks/{task_id}"),
        ("post", "/api/v1/account/companies/{company_id}/tasks/{task_id}/dispatch"),
        (
            "post",
            "/api/v1/account/companies/{company_id}/task-assignments/{task_assignment_id}/transition",
        ),
        ("get", "/api/v1/account/companies/{company_id}/tasks/{task_id}/photos"),
        ("post", "/api/v1/account/companies/{company_id}/tasks/{task_id}/photos"),
        (
            "get",
            "/api/v1/account/companies/{company_id}/tasks/{task_id}/photos/{photo_id}/content",
        ),
        (
            "delete",
            "/api/v1/account/companies/{company_id}/tasks/{task_id}/photos/{photo_id}",
        ),
    }
    assert expected == {
        (method, path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if (method, path) in expected
    }
    for method, path in expected:
        operation = schema["paths"][path][method]
        response_code = (
            "201" if method == "post" and path.endswith("/photos") else "200"
        )
        success_content = operation["responses"][response_code]["content"]
        if path.endswith("/content"):
            success = success_content["image/png"]["schema"]
            assert success == {"type": "string", "format": "binary"}
        else:
            success = success_content["application/json"]["schema"]
        assert success
        if path == "/api/v1/account/task-media/capability":
            assert set(operation["responses"]) == {"200", "401"}
        else:
            assert "409" in operation["responses"]
    schemas = schema["components"]["schemas"]
    for name in [
        "CreatePositionRequest",
        "JoinGroupInvitationRequest",
        "UpdateEmployeeBirthDateRequest",
        "CreateTaskRequest",
    ]:
        assert schemas[name]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_ten_worker_group_capacity_has_exactly_five_pending_profiles():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner, company = await create_company(setup, "Concurrent")
        _, _, invitation, token = await create_position_and_invitation(
            setup, owner, company, capacity=5
        )
        accounts = [
            await register_account(setup, f"Worker {index}") for index in range(10)
        ]
        company_id = company.company_id
        invitation_id = invitation["invitation_id"]
        await setup.commit()

    async def worker(index: int):
        async with AsyncSession(engine, expire_on_commit=False) as worker_session:
            try:
                result = await OrganizationWorkflowService(
                    worker_session, invitation_pepper=GROUP_PEPPER
                ).join_group_invitation(
                    JoinGroupInvitation(
                        accounts[index].id,
                        token,
                        uuid4(),
                        f"Worker {index}",
                        "Сотрудник",
                        date(1990, 1, index + 1),
                        NOW + timedelta(seconds=30),
                    )
                )
                await worker_session.commit()
                assert await worker_session.scalar(select(1)) == 1
                return result["status"]
            except OrganizationWorkflowUnavailable:
                await worker_session.rollback()
                assert await worker_session.scalar(select(1)) == 1
                return "capacity"

    results = await asyncio.gather(*(worker(index) for index in range(10)))
    assert results.count("pending_activation") == 5
    assert results.count("capacity") == 5
    async with AsyncSession(engine) as check:
        stored = await check.get(GroupInvitation, invitation_id)
        assert stored.registration_count == 5
        assert (
            await check.scalar(
                select(func.count())
                .select_from(EmployeeProfile)
                .where(
                    EmployeeProfile.company_id == company_id,
                    EmployeeProfile.employment_status == "pending_activation",
                )
            )
            == 5
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_ten_worker_task_photo_reservations_enforce_five_per_assignment():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        owner, company = await create_company(setup, "Concurrent task media")
        workflow, _, _, token = await create_position_and_invitation(
            setup, owner, company
        )
        employee, registration = await join_and_activate(
            setup, workflow, owner, company, token, "Фото concurrency"
        )
        draft = await workflow.create_task_draft(
            CreateTaskDraft(
                owner.id,
                company.company_id,
                company.venue_id,
                uuid4(),
                None,
                "Проверить выкладку",
                "Приложить фото",
                NOW + timedelta(seconds=60),
            )
        )
        await workflow.dispatch_task(
            DispatchTask(
                owner.id,
                company.company_id,
                draft["task_id"],
                (registration["employee_profile_id"],),
                1,
                NOW + timedelta(seconds=61),
            )
        )
        assignment_id = await setup.scalar(
            select(TaskAssignment.id).where(TaskAssignment.task_id == draft["task_id"])
        )
        photo_count_before = await setup.scalar(
            select(func.count()).select_from(TaskPhoto)
        )
        await setup.commit()

    async def worker(index: int):
        async with AsyncSession(engine, expire_on_commit=False) as worker_session:
            try:
                reserved = await TaskMediaService(worker_session).reserve(
                    ReserveTaskPhoto(
                        employee.id,
                        company.company_id,
                        draft["task_id"],
                        assignment_id,
                        "image/png",
                        PNG,
                        NOW + timedelta(seconds=62 + index),
                    )
                )
                await worker_session.commit()
                assert await worker_session.scalar(select(1)) == 1
                return ("reserved", reserved.photo_id)
            except OrganizationWorkflowInvalid:
                await worker_session.rollback()
                assert await worker_session.scalar(select(1)) == 1
                return ("limit", None)

    results = await asyncio.gather(*(worker(index) for index in range(10)))
    assert [status for status, _ in results].count("reserved") == 5
    assert [status for status, _ in results].count("limit") == 5
    assert len({photo_id for _, photo_id in results if photo_id is not None}) == 5
    async with AsyncSession(engine) as check:
        assert (
            await check.scalar(
                select(func.count())
                .select_from(TaskPhoto)
                .where(
                    TaskPhoto.task_id == draft["task_id"],
                    TaskPhoto.task_assignment_id == assignment_id,
                    TaskPhoto.media_status == "pending",
                )
            )
            == 5
        )
        assert (
            await check.scalar(select(func.count()).select_from(TaskPhoto))
            == photo_count_before + 5
        )
        assert await check.scalar(select(1)) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_private_minio_task_photo_lifecycle_and_authorization(session):
    endpoint = os.environ.get("TASK_MEDIA_TEST_ENDPOINT_URL")
    if not endpoint:
        pytest.skip("private MinIO contour is not configured")
    store = S3PrivateMediaStore(
        S3PrivateMediaStoreSettings(
            endpoint_url=endpoint,
            bucket=os.environ["TASK_MEDIA_TEST_BUCKET"],
            region=os.environ.get("TASK_MEDIA_TEST_REGION", "us-east-1"),
            access_key=os.environ["TASK_MEDIA_TEST_ACCESS_KEY"],
            secret_key=os.environ["TASK_MEDIA_TEST_SECRET_KEY"],
            ca_file=os.environ["TASK_MEDIA_TEST_CA_FILE"],
        )
    )
    await store.verify_security()
    owner, company = await create_company(session, "Private media")
    workflow, _, _, token = await create_position_and_invitation(
        session, owner, company
    )
    employee, registration = await join_and_activate(
        session, workflow, owner, company, token, "Фото сотрудник"
    )
    draft = await workflow.create_task_draft(
        CreateTaskDraft(
            owner.id,
            company.company_id,
            company.venue_id,
            uuid4(),
            None,
            "Зафиксировать результат",
            "Приложить фото",
            NOW + timedelta(seconds=6),
        )
    )
    await workflow.dispatch_task(
        DispatchTask(
            owner.id,
            company.company_id,
            draft["task_id"],
            (registration["employee_profile_id"],),
            1,
            NOW + timedelta(seconds=7),
        )
    )
    assignment = (
        await session.execute(
            select(TaskAssignment).where(TaskAssignment.task_id == draft["task_id"])
        )
    ).scalar_one()
    media = TaskMediaService(session)

    reserved = await media.reserve(
        ReserveTaskPhoto(
            employee.id,
            company.company_id,
            draft["task_id"],
            assignment.id,
            "image/png",
            PNG,
            NOW + timedelta(seconds=8),
        )
    )
    await store.put_temporary(
        reserved.temporary_object_key, reserved.content, reserved.mime_type
    )
    await store.promote(reserved.temporary_object_key, reserved.final_object_key)
    ready = await media.mark_ready(
        company.company_id,
        reserved.photo_id,
        reserved.digest,
        NOW + timedelta(seconds=9),
        reserved.final_object_key,
    )
    assert ready["status"] == "ready"
    assert set(ready).isdisjoint({"object_key", "sha256_digest"})
    employee_photos = await media.list_photos(
        employee.id,
        company.company_id,
        draft["task_id"],
        assignment.id,
        NOW + timedelta(seconds=10),
    )
    manager_photos = await media.list_photos(
        owner.id,
        company.company_id,
        draft["task_id"],
        assignment.id,
        NOW + timedelta(seconds=10),
    )
    assert employee_photos == manager_photos == [ready]
    authorized = await media.authorize_download(
        owner.id,
        company.company_id,
        reserved.photo_id,
        NOW + timedelta(seconds=10),
        task_id=draft["task_id"],
    )
    downloaded = await store.get(authorized.object_key, authorized.byte_size)
    assert downloaded == reserved.content

    outsider, foreign = await create_company(session, "Foreign media")
    assert foreign.company_id != company.company_id
    with pytest.raises(OrganizationWorkflowNotFound):
        await media.authorize_download(
            outsider.id,
            company.company_id,
            reserved.photo_id,
            NOW + timedelta(seconds=10),
            task_id=draft["task_id"],
        )

    removable = await media.reserve(
        ReserveTaskPhoto(
            employee.id,
            company.company_id,
            draft["task_id"],
            assignment.id,
            "image/png",
            PNG,
            NOW + timedelta(seconds=11),
        )
    )
    await store.put_temporary(
        removable.temporary_object_key, removable.content, removable.mime_type
    )
    await store.promote(removable.temporary_object_key, removable.final_object_key)
    await media.mark_ready(
        company.company_id,
        removable.photo_id,
        removable.digest,
        NOW + timedelta(seconds=12),
        removable.final_object_key,
    )
    deletion = await media.begin_delete(
        employee.id,
        company.company_id,
        draft["task_id"],
        removable.photo_id,
        NOW + timedelta(seconds=13),
    )
    await store.delete(deletion.object_key)
    deleted = await media.finalize_delete(
        company.company_id, removable.photo_id, NOW + timedelta(seconds=14)
    )
    assert deleted["status"] == "deleted"

    pending = await media.reserve(
        ReserveTaskPhoto(
            employee.id,
            company.company_id,
            draft["task_id"],
            assignment.id,
            "image/png",
            PNG,
            NOW + timedelta(seconds=15),
        )
    )
    await store.put_temporary(
        pending.temporary_object_key, pending.content, pending.mime_type
    )
    claimed = await media.claim_expired_pending(
        NOW + timedelta(hours=1), NOW + timedelta(hours=49)
    )
    matching = [item for item in claimed if item.photo_id == pending.photo_id]
    assert len(matching) == 1
    await store.delete(matching[0].object_key)
    await media.finalize_delete(
        company.company_id, pending.photo_id, NOW + timedelta(hours=49)
    )

    submitted = await workflow.transition_task_assignment(
        TransitionTaskAssignment(
            employee.id,
            company.company_id,
            assignment.id,
            "submit",
            assignment.version,
            NOW + timedelta(hours=50),
        )
    )
    assert submitted["status"] == "submitted_for_review"
    accepted = await workflow.transition_task_assignment(
        TransitionTaskAssignment(
            owner.id,
            company.company_id,
            assignment.id,
            "accept",
            submitted["version"],
            NOW + timedelta(hours=51),
        )
    )
    assert accepted["task_status"] == "completed"
    retained = await media.authorize_download(
        owner.id,
        company.company_id,
        reserved.photo_id,
        NOW + timedelta(hours=52),
        task_id=draft["task_id"],
    )
    assert await store.get(retained.object_key, retained.byte_size) == reserved.content
    with pytest.raises(OrganizationWorkflowNotFound):
        await media.begin_delete(
            owner.id,
            company.company_id,
            draft["task_id"],
            reserved.photo_id,
            NOW + timedelta(hours=52),
        )
    # Test teardown is not an application lifecycle deletion: the assertion
    # above proves retained evidence cannot be deleted through the product
    # service after review, while this removes only the synthetic object.
    await store.delete(retained.object_key)
    assert await session.scalar(select(1)) == 1
