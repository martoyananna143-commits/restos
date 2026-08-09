"""Standalone Account registration, password login, and password recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import hmac
from uuid import UUID, uuid4

import bcrypt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.account import Account, AccountIdentity
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    RegisterDeviceAndIssueSession,
    RevokeAllAccountSessions,
)
from app.internal.services.device_registration_challenge_service import (
    DeviceRegistrationChallengeService,
    DeviceRegistrationChallengeUnavailable,
)
from app.internal.services.invited_employee_registration_service import (
    BcryptPasswordHasher,
)
from app.internal.services.phone_verification_service import PhoneVerificationService


_PLATFORMS = {"ios", "android", "web", "desktop", "unknown"}
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"restos-non-enumerating-password-check", bcrypt.gensalt(rounds=12)
).decode("ascii")


class StandaloneAccountAuthError(Exception):
    """Base controlled standalone Account authentication error."""


class InvalidStandaloneAccountAuthRequest(StandaloneAccountAuthError):
    """Input shape or password bounds are invalid."""


class StandaloneAccountAuthUnavailable(StandaloneAccountAuthError):
    """Registration, login, or recovery is unavailable without enumeration."""


@dataclass(frozen=True)
class RegisterStandaloneAccount:
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
    now: datetime


@dataclass(frozen=True)
class LoginStandaloneAccount:
    phone: str
    password: str
    app_instance_id: UUID
    platform: str
    device_display_name: str | None
    public_key: bytes
    now: datetime


@dataclass(frozen=True)
class ResetStandaloneAccountPassword:
    phone_verification_challenge_id: UUID
    phone: str
    new_password: str
    now: datetime


@dataclass(frozen=True)
class AuthenticatedStandaloneAccount:
    account_id: UUID
    device_id: UUID
    session_id: UUID
    refresh_token: str
    absolute_expires_at: datetime
    display_name: str


@dataclass(frozen=True)
class ResetStandaloneAccountPasswordResult:
    account_id: UUID
    security_version: int
    revoked_session_count: int


class StandaloneAccountAuthService:
    """Compose existing Account primitives under caller-owned transactions."""

    def __init__(
        self,
        session: AsyncSession,
        account_sessions: AccountSessionService,
        device_challenges: DeviceRegistrationChallengeService,
        phone_pepper: bytes,
        password_hasher: BcryptPasswordHasher | None = None,
    ):
        if not isinstance(phone_pepper, bytes) or len(phone_pepper) < 32:
            raise ValueError("phone pepper must contain at least 32 bytes")
        self._session = session
        self._account_sessions = account_sessions
        self._device_challenges = device_challenges
        self._phone_pepper = phone_pepper
        self._password_hasher = password_hasher or BcryptPasswordHasher()

    async def register(
        self, request: RegisterStandaloneAccount
    ) -> AuthenticatedStandaloneAccount:
        phone = self._validate_common_device_input(request)
        self._validate_password(request.password)
        if not isinstance(request.display_name, str) or not request.display_name.strip():
            raise InvalidStandaloneAccountAuthRequest("display_name is required")
        display_name = request.display_name.strip()
        if len(display_name) > 255:
            raise InvalidStandaloneAccountAuthRequest("display_name is too long")
        phone_digest = self._phone_digest(phone)
        try:
            async with self._session.begin_nested():
                challenge = await self._verified_challenge(
                    request.phone_verification_challenge_id,
                    "account_registration",
                    phone_digest,
                    request.now,
                )
                if (
                    challenge.account_id is not None
                    or challenge.invitation_id is not None
                    or challenge.employee_profile_id is not None
                ):
                    raise StandaloneAccountAuthUnavailable(
                        "registration is unavailable"
                    )
                try:
                    device_challenge = (
                        await self._device_challenges.verify_account_registration_locked(
                            device_challenge_id=request.device_challenge_id,
                            nonce=request.device_challenge_nonce,
                            signature=request.device_challenge_signature,
                            phone_challenge_id=challenge.id,
                            app_instance_id=request.app_instance_id,
                            platform=request.platform,
                            now=request.now,
                        )
                    )
                except DeviceRegistrationChallengeUnavailable as error:
                    raise StandaloneAccountAuthUnavailable(
                        "registration is unavailable"
                    ) from error
                account = Account(
                    id=uuid4(),
                    display_name=display_name,
                    password_hash=self._password_hasher.hash(request.password),
                    pin_hash=None,
                    status="active",
                    security_version=1,
                    password_changed_at=request.now,
                    last_login_at=request.now,
                    created_at=request.now,
                    updated_at=request.now,
                    deleted_at=None,
                )
                self._session.add(account)
                await self._session.flush()
                identity = AccountIdentity(
                    id=uuid4(),
                    account_id=account.id,
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
                self._session.add(identity)
                await self._session.flush()
                issued = await self._account_sessions.register_device_and_issue_session(
                    RegisterDeviceAndIssueSession(
                        account_id=account.id,
                        app_instance_id=request.app_instance_id,
                        platform=request.platform,
                        display_name=request.device_display_name,
                        public_key=device_challenge.public_key,
                        now=request.now,
                    )
                )
                challenge.consumed_at = request.now
                challenge.consumed_by_account_id = account.id
                challenge.updated_at = request.now
                device_challenge.status = "consumed"
                device_challenge.consumed_at = request.now
                device_challenge.updated_at = request.now
                await self._session.flush()
                return self._authenticated(account, issued)
        except IntegrityError as error:
            if _constraint_name(error) == "uq_account_identities_active_external":
                raise StandaloneAccountAuthUnavailable(
                    "registration is unavailable"
                ) from error
            raise

    async def login(
        self, request: LoginStandaloneAccount
    ) -> AuthenticatedStandaloneAccount:
        phone = self._validate_login(request)
        digest = self._phone_digest(phone)
        async with self._session.begin_nested():
            identity = (
                await self._session.execute(
                    select(AccountIdentity).where(
                        AccountIdentity.identity_type == "phone",
                        AccountIdentity.provider == "e164",
                        AccountIdentity.subject_digest == digest,
                        AccountIdentity.status == "verified",
                        AccountIdentity.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            account = None
            if identity is not None:
                account = (
                    await self._session.execute(
                        select(Account)
                        .where(Account.id == identity.account_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
            encoded = (
                account.password_hash
                if account is not None and account.password_hash is not None
                else _DUMMY_PASSWORD_HASH
            )
            password_ok = self._password_hasher.verify(request.password, encoded)
            if (
                not password_ok
                or account is None
                or account.status != "active"
                or account.deleted_at is not None
            ):
                raise StandaloneAccountAuthUnavailable(
                    "authentication is unavailable"
                )
            issued = await self._account_sessions.register_device_and_issue_session(
                RegisterDeviceAndIssueSession(
                    account_id=account.id,
                    app_instance_id=request.app_instance_id,
                    platform=request.platform,
                    display_name=request.device_display_name,
                    public_key=request.public_key,
                    now=request.now,
                )
            )
            account.last_login_at = request.now
            account.updated_at = request.now
            await self._session.flush()
            return self._authenticated(account, issued)

    async def reset_password(
        self, request: ResetStandaloneAccountPassword
    ) -> ResetStandaloneAccountPasswordResult:
        self._require_uuid("phone_verification_challenge_id", request.phone_verification_challenge_id)
        self._require_aware(request.now)
        self._validate_password(request.new_password)
        try:
            phone = PhoneVerificationService.normalize_e164(request.phone)
        except Exception as error:
            raise InvalidStandaloneAccountAuthRequest("phone is invalid") from error
        digest = self._phone_digest(phone)
        async with self._session.begin_nested():
            challenge = await self._verified_challenge(
                request.phone_verification_challenge_id,
                "password_reset",
                digest,
                request.now,
            )
            if challenge.account_id is None:
                raise StandaloneAccountAuthUnavailable("recovery is unavailable")
            identity = (
                await self._session.execute(
                    select(AccountIdentity).where(
                        AccountIdentity.account_id == challenge.account_id,
                        AccountIdentity.identity_type == "phone",
                        AccountIdentity.provider == "e164",
                        AccountIdentity.subject_digest == digest,
                        AccountIdentity.status == "verified",
                        AccountIdentity.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if identity is None:
                raise StandaloneAccountAuthUnavailable("recovery is unavailable")
            account = (
                await self._session.execute(
                    select(Account)
                    .where(Account.id == challenge.account_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                account is None
                or account.status != "active"
                or account.deleted_at is not None
            ):
                raise StandaloneAccountAuthUnavailable("recovery is unavailable")
            account.password_hash = self._password_hasher.hash(request.new_password)
            account.password_changed_at = request.now
            account.updated_at = request.now
            revoked = await self._account_sessions.revoke_all_account_sessions(
                RevokeAllAccountSessions(account_id=account.id, now=request.now)
            )
            challenge.consumed_at = request.now
            challenge.consumed_by_account_id = account.id
            challenge.updated_at = request.now
            await self._session.flush()
            return ResetStandaloneAccountPasswordResult(
                account_id=account.id,
                security_version=revoked.security_version,
                revoked_session_count=revoked.revoked_session_count,
            )

    async def _verified_challenge(
        self,
        challenge_id: UUID,
        purpose: str,
        phone_digest: bytes,
        now: datetime,
    ) -> PhoneVerificationChallenge:
        challenge = (
            await self._session.execute(
                select(PhoneVerificationChallenge)
                .where(PhoneVerificationChallenge.id == challenge_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            challenge is None
            or challenge.purpose != purpose
            or challenge.status != "verified"
            or challenge.consumed_at is not None
            or challenge.expires_at <= now
            or not hmac.compare_digest(challenge.phone_digest, phone_digest)
        ):
            raise StandaloneAccountAuthUnavailable("operation is unavailable")
        return challenge

    def _validate_common_device_input(self, request: RegisterStandaloneAccount) -> str:
        for name in (
            "phone_verification_challenge_id",
            "app_instance_id",
            "device_challenge_id",
        ):
            self._require_uuid(name, getattr(request, name))
        self._validate_device_parts(
            request.platform,
            request.device_display_name,
            request.device_challenge_nonce,
            request.device_challenge_signature,
            request.now,
        )
        try:
            return PhoneVerificationService.normalize_e164(request.phone)
        except Exception as error:
            raise InvalidStandaloneAccountAuthRequest("phone is invalid") from error

    def _validate_login(self, request: LoginStandaloneAccount) -> str:
        self._require_uuid("app_instance_id", request.app_instance_id)
        self._require_aware(request.now)
        self._validate_password(request.password, minimum=False)
        if request.platform not in _PLATFORMS:
            raise InvalidStandaloneAccountAuthRequest("platform is invalid")
        if request.device_display_name is not None and (
            not isinstance(request.device_display_name, str)
            or len(request.device_display_name) > 255
        ):
            raise InvalidStandaloneAccountAuthRequest("device display name is invalid")
        if not isinstance(request.public_key, bytes) or not request.public_key:
            raise InvalidStandaloneAccountAuthRequest("public key is invalid")
        try:
            return PhoneVerificationService.normalize_e164(request.phone)
        except Exception as error:
            raise InvalidStandaloneAccountAuthRequest("phone is invalid") from error

    def _validate_device_parts(
        self,
        platform: str,
        display_name: str | None,
        nonce: bytes,
        signature: bytes,
        now: datetime,
    ) -> None:
        self._require_aware(now)
        if platform not in _PLATFORMS:
            raise InvalidStandaloneAccountAuthRequest("platform is invalid")
        if display_name is not None and (
            not isinstance(display_name, str) or len(display_name) > 255
        ):
            raise InvalidStandaloneAccountAuthRequest("device display name is invalid")
        if not isinstance(nonce, bytes) or len(nonce) != 32:
            raise InvalidStandaloneAccountAuthRequest("device proof is invalid")
        if not isinstance(signature, bytes) or not signature:
            raise InvalidStandaloneAccountAuthRequest("device proof is invalid")

    @staticmethod
    def _validate_password(password: str, minimum: bool = True) -> None:
        if not isinstance(password, str):
            raise InvalidStandaloneAccountAuthRequest("password is invalid")
        raw = password.encode("utf-8")
        if len(raw) > 72 or (minimum and len(password) < 12):
            raise InvalidStandaloneAccountAuthRequest("password is invalid")

    def _phone_digest(self, phone: str) -> bytes:
        return hmac.new(
            self._phone_pepper, phone.encode("ascii"), hashlib.sha256
        ).digest()

    @staticmethod
    def _authenticated(account, issued) -> AuthenticatedStandaloneAccount:
        return AuthenticatedStandaloneAccount(
            account_id=account.id,
            device_id=issued.device_id,
            session_id=issued.session_id,
            refresh_token=issued.refresh_token,
            absolute_expires_at=issued.absolute_expires_at,
            display_name=account.display_name,
        )

    @staticmethod
    def _require_uuid(name: str, value: UUID) -> None:
        if not isinstance(value, UUID):
            raise InvalidStandaloneAccountAuthRequest(f"{name} must be a UUID")

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise InvalidStandaloneAccountAuthRequest("now must be timezone-aware")


def _constraint_name(error: IntegrityError) -> str | None:
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
