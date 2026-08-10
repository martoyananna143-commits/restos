"""Atomic registration orchestration for an invited workforce employee."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
import re
from typing import Protocol
from uuid import UUID, uuid4

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.account import Account, AccountIdentity
from app.infra.database.models.account_legal_acceptance import AccountLegalAcceptance
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import Invitation
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    RegisterDeviceAndIssueSession,
)
from app.internal.services.account_legal_contract import (
    ACCOUNT_REGISTRATION_CONTEXT,
    PRIVACY_DOCUMENT_SHA256,
    TERMS_DOCUMENT_SHA256,
    AccountRegistrationAcceptance,
    require_account_registration_acceptance,
)
from app.internal.services.device_registration_challenge_service import (
    DeviceRegistrationChallengeService,
    DeviceRegistrationChallengeUnavailable,
)
from app.internal.services.phone_verification_service import PhoneVerificationService
from app.internal.services.workforce_invitation_service import (
    AcceptWorkforceInvitation,
    WorkforceInvitationService,
)


_SIX_ASCII_DIGITS = re.compile(r"^[0-9]{6}$")
_ALLOWED_PLATFORMS = {"ios", "android", "web", "desktop", "unknown"}


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password: str, encoded: str) -> bool: ...


class BcryptPasswordHasher:
    """bcrypt adapter that rejects, rather than truncates, inputs over 72 bytes."""

    def hash(self, password: str) -> str:
        raw = password.encode("utf-8")
        if len(raw) > 72:
            raise InvalidInvitedEmployeeRegistration(
                "password must not exceed 72 UTF-8 bytes"
            )
        return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")

    def verify(self, password: str, encoded: str) -> bool:
        raw = password.encode("utf-8")
        if len(raw) > 72:
            return False
        try:
            return bcrypt.checkpw(raw, encoded.encode("ascii"))
        except (ValueError, UnicodeError):
            return False


class InvitedEmployeeRegistrationError(Exception):
    """Base controlled registration error."""


class InvalidInvitedEmployeeRegistration(InvitedEmployeeRegistrationError):
    """Runtime input is invalid."""


class InvitedEmployeeRegistrationUnavailable(InvitedEmployeeRegistrationError):
    """Invitation, profile, or verified phone challenge is unavailable."""


@dataclass(frozen=True)
class RegisterInvitedEmployee:
    invitation_code: str
    phone_verification_challenge_id: UUID
    phone: str
    display_name: str
    password: str
    app_instance_id: UUID
    platform: str
    device_display_name: str | None
    device_challenge_id: UUID
    device_challenge_nonce: bytes
    device_challenge_signature: bytes
    legal_acceptance: AccountRegistrationAcceptance
    now: datetime


@dataclass(frozen=True)
class RegisteredInvitedEmployee:
    account_id: UUID
    employee_profile_id: UUID
    employee_assignment_id: UUID
    company_id: UUID
    device_id: UUID
    session_id: UUID
    refresh_token: str
    display_name: str


class InvitedEmployeeRegistrationService:
    """Compose verified services under one outer database savepoint."""

    def __init__(
        self,
        session: AsyncSession,
        workforce_invitations: WorkforceInvitationService,
        account_sessions: AccountSessionService,
        device_challenges: DeviceRegistrationChallengeService,
        invitation_pepper: bytes,
        phone_pepper: bytes,
        password_hasher: PasswordHasher | None = None,
    ):
        if not isinstance(invitation_pepper, bytes) or len(invitation_pepper) < 32:
            raise ValueError("invitation pepper must contain at least 32 bytes")
        if not isinstance(phone_pepper, bytes) or len(phone_pepper) < 32:
            raise ValueError("phone pepper must contain at least 32 bytes")
        self._session = session
        self._workforce = workforce_invitations
        self._account_sessions = account_sessions
        self._device_challenges = device_challenges
        self._invitation_pepper = invitation_pepper
        self._phone_pepper = phone_pepper
        self._password_hasher = password_hasher or BcryptPasswordHasher()

    async def register(
        self, request: RegisterInvitedEmployee
    ) -> RegisteredInvitedEmployee:
        normalized_phone = self._validate_input(request)
        require_account_registration_acceptance(request.legal_acceptance)
        invitation_digest = hmac.new(
            self._invitation_pepper,
            request.invitation_code.encode("ascii"),
            hashlib.sha256,
        ).digest()
        phone_digest = hmac.new(
            self._phone_pepper, normalized_phone.encode("ascii"), hashlib.sha256
        ).digest()

        async with self._session.begin_nested():
            invitation = (
                await self._session.execute(
                    select(Invitation)
                    .where(
                        Invitation.code_digest == invitation_digest,
                        Invitation.status == "pending",
                        Invitation.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                invitation is None
                or not hmac.compare_digest(invitation.code_digest, invitation_digest)
                or invitation.expires_at <= request.now
            ):
                raise InvitedEmployeeRegistrationUnavailable(
                    "registration is unavailable"
                )

            phone_challenge = (
                await self._session.execute(
                    select(PhoneVerificationChallenge)
                    .where(
                        PhoneVerificationChallenge.id
                        == request.phone_verification_challenge_id
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                phone_challenge is None
                or phone_challenge.purpose != "invitation_registration"
                or phone_challenge.status != "verified"
                or phone_challenge.consumed_at is not None
                or phone_challenge.expires_at <= request.now
                or phone_challenge.invitation_id != invitation.id
                or phone_challenge.employee_profile_id != invitation.employee_profile_id
                or not hmac.compare_digest(phone_challenge.phone_digest, phone_digest)
            ):
                raise InvitedEmployeeRegistrationUnavailable(
                    "registration is unavailable"
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
                or profile.phone is None
            ):
                raise InvitedEmployeeRegistrationUnavailable(
                    "registration is unavailable"
                )
            try:
                profile_phone = PhoneVerificationService.normalize_e164(profile.phone)
            except Exception as error:
                raise InvitedEmployeeRegistrationUnavailable(
                    "registration is unavailable"
                ) from error
            if not hmac.compare_digest(
                profile_phone.encode("ascii"), normalized_phone.encode("ascii")
            ):
                raise InvitedEmployeeRegistrationUnavailable(
                    "registration is unavailable"
                )

            try:
                device_challenge = await self._device_challenges.verify_locked(
                    device_challenge_id=request.device_challenge_id,
                    nonce=request.device_challenge_nonce,
                    signature=request.device_challenge_signature,
                    invitation_id=invitation.id,
                    phone_challenge_id=phone_challenge.id,
                    employee_profile_id=profile.id,
                    app_instance_id=request.app_instance_id,
                    platform=request.platform,
                    now=request.now,
                )
            except DeviceRegistrationChallengeUnavailable as error:
                raise InvitedEmployeeRegistrationUnavailable(
                    "registration is unavailable"
                ) from error

            account_id = uuid4()
            password_hash = self._password_hasher.hash(request.password)
            account = Account(
                id=account_id,
                display_name=request.display_name.strip(),
                password_hash=password_hash,
                pin_hash=None,
                status="active",
                security_version=1,
                password_changed_at=request.now,
                last_login_at=request.now,
                created_at=request.now,
                updated_at=request.now,
            )
            identity = AccountIdentity(
                id=uuid4(),
                account_id=account_id,
                identity_type="phone",
                provider="e164",
                subject_digest=phone_digest,
                subject_ciphertext=None,
                passkey_credential_id=None,
                passkey_public_key=None,
                sign_count=None,
                verified_at=request.now,
                is_primary=True,
                status="verified",
                identity_metadata={},
                created_at=request.now,
                updated_at=request.now,
                deleted_at=None,
            )
            self._session.add(account)
            await self._session.flush()
            self._session.add(
                AccountLegalAcceptance(
                    id=uuid4(),
                    account_id=account_id,
                    context=ACCOUNT_REGISTRATION_CONTEXT,
                    document_set_version=request.legal_acceptance.document_set_version,
                    terms_version=request.legal_acceptance.terms_version,
                    terms_document_sha256=TERMS_DOCUMENT_SHA256,
                    privacy_version=request.legal_acceptance.privacy_version,
                    privacy_document_sha256=PRIVACY_DOCUMENT_SHA256,
                    accepted_at=request.now,
                    created_at=request.now,
                )
            )
            await self._session.flush()
            self._session.add(identity)
            await self._session.flush()

            accepted = await self._workforce.accept(
                AcceptWorkforceInvitation(
                    account_id=account_id,
                    code=request.invitation_code,
                    now=request.now,
                )
            )
            issued = await self._account_sessions.register_device_and_issue_session(
                RegisterDeviceAndIssueSession(
                    account_id=account_id,
                    app_instance_id=request.app_instance_id,
                    platform=request.platform,
                    display_name=request.device_display_name,
                    public_key=device_challenge.public_key,
                    now=request.now,
                )
            )
            phone_challenge.consumed_at = request.now
            phone_challenge.consumed_by_account_id = account_id
            phone_challenge.updated_at = request.now
            device_challenge.status = "consumed"
            device_challenge.consumed_at = request.now
            device_challenge.updated_at = request.now
            await self._session.flush()
            return RegisteredInvitedEmployee(
                account_id=account_id,
                employee_profile_id=accepted.employee_profile_id,
                employee_assignment_id=accepted.employee_assignment_id,
                company_id=accepted.company_id,
                device_id=issued.device_id,
                session_id=issued.session_id,
                refresh_token=issued.refresh_token,
                display_name=account.display_name,
            )

    def _validate_input(self, request: RegisterInvitedEmployee) -> str:
        if not isinstance(request.invitation_code, str) or not _SIX_ASCII_DIGITS.fullmatch(
            request.invitation_code
        ):
            raise InvalidInvitedEmployeeRegistration(
                "invitation code must be six ASCII digits"
            )
        for name in (
            "phone_verification_challenge_id",
            "app_instance_id",
            "device_challenge_id",
        ):
            if not isinstance(getattr(request, name), UUID):
                raise InvalidInvitedEmployeeRegistration(f"{name} must be a UUID")
        if not isinstance(request.display_name, str) or not request.display_name.strip():
            raise InvalidInvitedEmployeeRegistration("display_name is required")
        if len(request.display_name.strip()) > 255:
            raise InvalidInvitedEmployeeRegistration("display_name is too long")
        if not isinstance(request.password, str) or len(request.password) < 12:
            raise InvalidInvitedEmployeeRegistration(
                "password must contain at least 12 characters"
            )
        if len(request.password.encode("utf-8")) > 72:
            raise InvalidInvitedEmployeeRegistration(
                "password must not exceed 72 UTF-8 bytes"
            )
        if not isinstance(request.platform, str) or request.platform not in _ALLOWED_PLATFORMS:
            raise InvalidInvitedEmployeeRegistration("platform is invalid")
        if request.device_display_name is not None and not isinstance(
            request.device_display_name, str
        ):
            raise InvalidInvitedEmployeeRegistration(
                "device_display_name must be a string"
            )
        if request.device_display_name is not None and len(request.device_display_name) > 255:
            raise InvalidInvitedEmployeeRegistration("device_display_name is too long")
        if (
            not isinstance(request.device_challenge_nonce, bytes)
            or len(request.device_challenge_nonce) != 32
            or not isinstance(request.device_challenge_signature, bytes)
            or not request.device_challenge_signature
        ):
            raise InvalidInvitedEmployeeRegistration("device proof is invalid")
        if not isinstance(request.now, datetime) or request.now.tzinfo is None or request.now.utcoffset() is None:
            raise InvalidInvitedEmployeeRegistration("now must be timezone-aware")
        try:
            return PhoneVerificationService.normalize_e164(request.phone)
        except Exception as error:
            raise InvalidInvitedEmployeeRegistration("phone is invalid") from error
