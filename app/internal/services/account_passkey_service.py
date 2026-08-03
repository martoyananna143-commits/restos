"""WebAuthn passkeys with separate Stage 20B device proof-of-possession."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    byteslike_to_bytes,
    parse_authentication_credential_json,
    parse_client_data_json,
    parse_registration_credential_json,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    CredentialDeviceType,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.infra.database.models.account import (
    Account,
    AccountDevice,
    AccountIdentity,
    AccountSession,
)
from app.infra.database.models.account_webauthn_challenge import (
    AccountWebAuthnChallenge,
)
from app.internal.services.account_session_service import (
    AccountSessionService,
    AccountSessionServiceError,
    IssuedDeviceSession,
    RegisterDeviceAndIssueSession,
)


_PLATFORMS = {"ios", "android", "web", "desktop", "unknown"}
_DEVICE_PROTOCOL = b"restos-passkey-login-device-v1"
_AUTH_BEGIN_LOCK_DOMAIN = b"restos-passkey-auth-begin-advisory-v1"
_MAX_DISPLAY_NAME = 255
_MAX_PENDING_BEGIN = 5
_ALLOWED_TRANSPORTS = {
    "ble",
    "hybrid",
    "internal",
    "nfc",
    "smart-card",
    "usb",
}


class AccountPasskeyServiceError(Exception):
    """Base controlled passkey-service error."""


class InvalidAccountPasskeyRequest(AccountPasskeyServiceError):
    """Runtime request data is malformed."""


class AccountPasskeyUnavailable(AccountPasskeyServiceError):
    """A passkey operation is unavailable without disclosing why."""


class AccountPasskeyRateLimited(AccountPasskeyServiceError):
    """The server-side challenge bucket is exhausted."""


@dataclass(frozen=True)
class PasskeyOptions:
    challenge_id: UUID
    public_key: dict[str, Any]
    expires_at: datetime


@dataclass(frozen=True)
class RegistrationVerified:
    identity_id: UUID
    display_name: str | None


@dataclass(frozen=True)
class AuthenticationVerified:
    account_id: UUID
    device_session: IssuedDeviceSession


@dataclass(frozen=True)
class PasskeyRejected:
    attempts: int


@dataclass(frozen=True)
class PasskeySummary:
    identity_id: UUID
    display_name: str | None
    transports: tuple[str, ...]
    backup_eligible: bool
    backup_state: bool
    created_at: datetime
    last_used_at: datetime | None
    status: str
    revoked_at: datetime | None


def _field(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def _signed_bigint(value: bytes) -> int:
    if not isinstance(value, bytes) or len(value) != 8:
        raise ValueError("advisory lock material is invalid")
    return int.from_bytes(value, byteorder="big", signed=True)


def authentication_bucket_lock_key(bucket_digest: bytes) -> int:
    """Map a secret-derived bucket digest to a namespaced PostgreSQL BIGINT."""

    if not isinstance(bucket_digest, bytes) or len(bucket_digest) != 32:
        raise ValueError("rate-limit bucket digest is invalid")
    namespaced = hashlib.sha256(
        _AUTH_BEGIN_LOCK_DOMAIN + bucket_digest
    ).digest()
    return _signed_bigint(namespaced[:8])


def canonical_passkey_device_message(
    *,
    authentication_challenge_id: UUID,
    webauthn_challenge: bytes,
    app_instance_id: UUID,
    platform: str,
    public_key: bytes,
    credential_id: bytes,
) -> bytes:
    """Return the exact Stage 22A device proof message."""

    return b"".join(
        _field(value)
        for value in (
            _DEVICE_PROTOCOL,
            authentication_challenge_id.bytes,
            webauthn_challenge,
            app_instance_id.bytes,
            platform.encode("ascii"),
            hashlib.sha256(public_key).digest(),
            hashlib.sha256(credential_id).digest(),
        )
    )


def credential_device_type_is_backup_eligible(
    credential_device_type: CredentialDeviceType,
) -> bool:
    """Map the verified WebAuthn credential device type to its immutable BE bit."""

    if credential_device_type == CredentialDeviceType.SINGLE_DEVICE:
        return False
    if credential_device_type == CredentialDeviceType.MULTI_DEVICE:
        return True
    raise ValueError("credential device type is unavailable")


class AccountPasskeyService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        rp_id: str,
        rp_name: str,
        allowed_origins: tuple[str, ...],
        session_pepper: bytes,
        challenge_ttl: timedelta,
        max_verify_attempts: int,
    ):
        if not isinstance(rp_id, str) or not rp_id:
            raise ValueError("WebAuthn configuration is unavailable")
        if not isinstance(rp_name, str) or not rp_name.strip():
            raise ValueError("WebAuthn configuration is unavailable")
        if not allowed_origins or not all(
            isinstance(origin, str) and origin for origin in allowed_origins
        ):
            raise ValueError("WebAuthn configuration is unavailable")
        if not isinstance(session_pepper, bytes) or len(session_pepper) < 32:
            raise ValueError("WebAuthn configuration is unavailable")
        if not isinstance(challenge_ttl, timedelta) or challenge_ttl <= timedelta(0):
            raise ValueError("WebAuthn configuration is unavailable")
        if (
            isinstance(max_verify_attempts, bool)
            or not isinstance(max_verify_attempts, int)
            or max_verify_attempts < 1
        ):
            raise ValueError("WebAuthn configuration is unavailable")
        self._session = session
        self._rp_id = rp_id
        self._rp_name = rp_name.strip()
        self._origins = list(allowed_origins)
        self._pepper = session_pepper
        self._ttl = challenge_ttl
        self._max_attempts = max_verify_attempts

    async def begin_registration(
        self, account_id: UUID, session_id: UUID, now: datetime
    ) -> PasskeyOptions:
        self._uuid("account_id", account_id)
        self._uuid("session_id", session_id)
        self._aware(now)
        async with self._session.begin_nested():
            account, account_session, device = await self._authenticated_context(
                account_id, session_id, now, lock=True
            )
            del device
            pending_count = (
                await self._session.execute(
                    select(func.count())
                    .select_from(AccountWebAuthnChallenge)
                    .where(
                        AccountWebAuthnChallenge.ceremony_type == "registration",
                        AccountWebAuthnChallenge.account_id == account.id,
                        AccountWebAuthnChallenge.status == "pending",
                        AccountWebAuthnChallenge.expires_at > now,
                    )
                )
            ).scalar_one()
            if pending_count >= _MAX_PENDING_BEGIN:
                raise AccountPasskeyRateLimited("passkey operation is unavailable")
            identities = list(
                (
                    await self._session.execute(
                        select(AccountIdentity).where(
                            AccountIdentity.account_id == account.id,
                            AccountIdentity.identity_type == "passkey",
                            AccountIdentity.status == "verified",
                            AccountIdentity.deleted_at.is_(None),
                        )
                    )
                ).scalars()
            )
            raw_challenge = secrets.token_bytes(32)
            challenge = AccountWebAuthnChallenge(
                id=uuid4(),
                ceremony_type="registration",
                challenge_digest=hashlib.sha256(raw_challenge).digest(),
                account_id=account.id,
                session_id=account_session.id,
                device_context_digest=None,
                app_instance_id=None,
                platform=None,
                device_display_name=None,
                rate_limit_key_digest=None,
                attempts=0,
                status="pending",
                expires_at=now + self._ttl,
                consumed_at=None,
                created_at=now,
                updated_at=now,
            )
            self._session.add(challenge)
            await self._session.flush()
            options = generate_registration_options(
                rp_id=self._rp_id,
                rp_name=self._rp_name,
                user_id=account.id.bytes,
                user_name=str(account.id),
                user_display_name=account.display_name,
                challenge=raw_challenge,
                timeout=int(self._ttl.total_seconds() * 1000),
                attestation=AttestationConveyancePreference.NONE,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    require_resident_key=True,
                    user_verification=UserVerificationRequirement.REQUIRED,
                ),
                exclude_credentials=[
                    PublicKeyCredentialDescriptor(id=identity.passkey_credential_id)
                    for identity in identities
                    if identity.passkey_credential_id is not None
                ],
                supported_pub_key_algs=[
                    COSEAlgorithmIdentifier.ECDSA_SHA_256
                ],
            )
            return PasskeyOptions(
                challenge.id,
                json.loads(options_to_json(options)),
                challenge.expires_at,
            )

    async def verify_registration(
        self,
        *,
        challenge_id: UUID,
        account_id: UUID,
        session_id: UUID,
        credential: dict[str, Any],
        display_name: str | None,
        now: datetime,
    ) -> RegistrationVerified | PasskeyRejected:
        self._uuid("challenge_id", challenge_id)
        self._uuid("account_id", account_id)
        self._uuid("session_id", session_id)
        self._aware(now)
        normalized_name = self._display_name(display_name)
        async with self._session.begin_nested():
            challenge = await self._lock_challenge(challenge_id)
            if not self._challenge_available(
                challenge, "registration", now
            ) or challenge.account_id != account_id or challenge.session_id != session_id:
                return await self._reject(challenge, now)
            try:
                parsed = parse_registration_credential_json(credential)
                client_data = parse_client_data_json(
                    byteslike_to_bytes(parsed.response.client_data_json)
                )
                raw_challenge = client_data.challenge
                if not hmac.compare_digest(
                    challenge.challenge_digest,
                    hashlib.sha256(raw_challenge).digest(),
                ):
                    raise InvalidRegistrationResponse("challenge unavailable")
                account, _session, _device = await self._authenticated_context(
                    account_id, session_id, now, lock=True
                )
                verified = verify_registration_response(
                    credential=parsed,
                    expected_challenge=raw_challenge,
                    expected_rp_id=self._rp_id,
                    expected_origin=self._origins,
                    require_user_presence=True,
                    require_user_verification=True,
                    supported_pub_key_algs=[
                        COSEAlgorithmIdentifier.ECDSA_SHA_256
                    ],
                )
                duplicate = (
                    await self._session.execute(
                        select(AccountIdentity)
                        .where(
                            AccountIdentity.identity_type == "passkey",
                            AccountIdentity.passkey_credential_id
                            == verified.credential_id,
                            AccountIdentity.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if duplicate is not None:
                    raise InvalidRegistrationResponse("credential unavailable")
                transports = self._transports(parsed.response.transports)
                backup_eligible = credential_device_type_is_backup_eligible(
                    verified.credential_device_type
                )
                if verified.credential_backed_up and not backup_eligible:
                    raise InvalidRegistrationResponse("credential unavailable")
                try:
                    async with self._session.begin_nested():
                        identity = AccountIdentity(
                            id=uuid4(),
                            account_id=account.id,
                            identity_type="passkey",
                            provider="webauthn",
                            subject_digest=None,
                            subject_ciphertext=None,
                            passkey_credential_id=verified.credential_id,
                            passkey_public_key=verified.credential_public_key,
                            sign_count=verified.sign_count,
                            passkey_transports=list(transports),
                            passkey_backup_eligible=backup_eligible,
                            passkey_backup_state=verified.credential_backed_up,
                            passkey_display_name=normalized_name,
                            passkey_last_used_at=None,
                            passkey_revoked_at=None,
                            passkey_revoked_reason=None,
                            verified_at=now,
                            is_primary=False,
                            status="verified",
                            identity_metadata={},
                            created_at=now,
                            updated_at=now,
                            deleted_at=None,
                        )
                        self._session.add(identity)
                        challenge.status = "consumed"
                        challenge.consumed_at = now
                        challenge.updated_at = now
                        await self._session.flush()
                except IntegrityError:
                    challenge = await self._lock_challenge(challenge_id)
                    return await self._reject(challenge, now)
                return RegistrationVerified(identity.id, normalized_name)
            except (
                InvalidRegistrationResponse,
                ValueError,
                TypeError,
            ):
                return await self._reject(challenge, now)

    async def begin_authentication(
        self,
        *,
        app_instance_id: UUID,
        platform: str,
        display_name: str | None,
        public_key: bytes,
        rate_limit_subject: bytes,
        now: datetime,
    ) -> PasskeyOptions:
        self._uuid("app_instance_id", app_instance_id)
        self._aware(now)
        platform = self._platform(platform)
        display_name = self._display_name(display_name)
        canonical_key = self._device_public_key(public_key)
        context_digest = self._device_context_digest(
            app_instance_id, platform, canonical_key
        )
        if not isinstance(rate_limit_subject, bytes) or not rate_limit_subject:
            raise InvalidAccountPasskeyRequest("rate-limit subject is invalid")
        bucket = hmac.new(
            self._pepper,
            b"webauthn-auth-begin-v1"
            + rate_limit_subject
            + context_digest,
            hashlib.sha256,
        ).digest()
        async with self._session.begin_nested():
            await self._session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        authentication_bucket_lock_key(bucket)
                    )
                )
            )
            pending_count = (
                await self._session.execute(
                    select(func.count())
                    .select_from(AccountWebAuthnChallenge)
                    .where(
                        AccountWebAuthnChallenge.ceremony_type == "authentication",
                        AccountWebAuthnChallenge.rate_limit_key_digest == bucket,
                        AccountWebAuthnChallenge.status == "pending",
                        AccountWebAuthnChallenge.expires_at > now,
                    )
                )
            ).scalar_one()
            if pending_count >= _MAX_PENDING_BEGIN:
                raise AccountPasskeyRateLimited("passkey operation is unavailable")
            raw_challenge = secrets.token_bytes(32)
            challenge = AccountWebAuthnChallenge(
                id=uuid4(),
                ceremony_type="authentication",
                challenge_digest=hashlib.sha256(raw_challenge).digest(),
                account_id=None,
                session_id=None,
                device_context_digest=context_digest,
                app_instance_id=app_instance_id,
                platform=platform,
                device_display_name=display_name,
                rate_limit_key_digest=bucket,
                attempts=0,
                status="pending",
                expires_at=now + self._ttl,
                consumed_at=None,
                created_at=now,
                updated_at=now,
            )
            self._session.add(challenge)
            await self._session.flush()
            options = generate_authentication_options(
                rp_id=self._rp_id,
                challenge=raw_challenge,
                timeout=int(self._ttl.total_seconds() * 1000),
                allow_credentials=[],
                user_verification=UserVerificationRequirement.REQUIRED,
            )
            serialized = json.loads(options_to_json(options))
            if serialized.get("allowCredentials") not in (None, []):
                raise RuntimeError("discoverable credentials are unavailable")
            return PasskeyOptions(
                challenge.id, serialized, challenge.expires_at
            )

    async def verify_authentication(
        self,
        *,
        challenge_id: UUID,
        credential: dict[str, Any],
        app_instance_id: UUID,
        platform: str,
        display_name: str | None,
        public_key: bytes,
        device_signature: bytes,
        session_service: AccountSessionService,
        now: datetime,
    ) -> AuthenticationVerified | PasskeyRejected:
        self._uuid("challenge_id", challenge_id)
        self._uuid("app_instance_id", app_instance_id)
        self._aware(now)
        platform = self._platform(platform)
        del display_name
        canonical_key = self._device_public_key(public_key)
        if not isinstance(device_signature, bytes) or not device_signature:
            raise InvalidAccountPasskeyRequest("device signature is invalid")
        async with self._session.begin_nested():
            challenge = await self._lock_challenge(challenge_id)
            if not self._challenge_available(challenge, "authentication", now):
                return await self._reject(challenge, now)
            try:
                context_digest = self._device_context_digest(
                    app_instance_id, platform, canonical_key
                )
                if (
                    challenge.app_instance_id != app_instance_id
                    or challenge.platform != platform
                    or not hmac.compare_digest(
                        challenge.device_context_digest or b"",
                        context_digest,
                    )
                ):
                    raise InvalidAuthenticationResponse("authentication unavailable")
                parsed = parse_authentication_credential_json(credential)
                client_data = parse_client_data_json(
                    byteslike_to_bytes(parsed.response.client_data_json)
                )
                raw_challenge = client_data.challenge
                if not hmac.compare_digest(
                    challenge.challenge_digest,
                    hashlib.sha256(raw_challenge).digest(),
                ):
                    raise InvalidAuthenticationResponse("authentication unavailable")
                credential_id = parsed.raw_id
                identity = (
                    await self._session.execute(
                        select(AccountIdentity)
                        .where(
                            AccountIdentity.identity_type == "passkey",
                            AccountIdentity.passkey_credential_id == credential_id,
                            AccountIdentity.deleted_at.is_(None),
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if (
                    identity is None
                    or identity.status != "verified"
                    or identity.passkey_public_key is None
                    or identity.sign_count is None
                    or identity.passkey_backup_eligible is None
                ):
                    raise InvalidAuthenticationResponse("authentication unavailable")
                verified = verify_authentication_response(
                    credential=parsed,
                    expected_challenge=raw_challenge,
                    expected_rp_id=self._rp_id,
                    expected_origin=self._origins,
                    credential_public_key=identity.passkey_public_key,
                    credential_current_sign_count=(
                        0
                        if identity.passkey_backup_eligible
                        else identity.sign_count
                    ),
                    require_user_verification=True,
                )
                backup_eligible = credential_device_type_is_backup_eligible(
                    verified.credential_device_type
                )
                if backup_eligible != identity.passkey_backup_eligible or (
                    verified.credential_backed_up and not backup_eligible
                ):
                    raise InvalidAuthenticationResponse(
                        "authentication unavailable"
                    )
                user_handle = parsed.response.user_handle
                if user_handle is None:
                    raise InvalidAuthenticationResponse("authentication unavailable")
                account = (
                    await self._session.execute(
                        select(Account)
                        .where(Account.id == identity.account_id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if (
                    account is None
                    or account.status != "active"
                    or account.deleted_at is not None
                    or byteslike_to_bytes(user_handle) != account.id.bytes
                ):
                    raise InvalidAuthenticationResponse("authentication unavailable")
                self._verify_device_signature(
                    public_key=canonical_key,
                    signature=device_signature,
                    message=canonical_passkey_device_message(
                        authentication_challenge_id=challenge.id,
                        webauthn_challenge=raw_challenge,
                        app_instance_id=app_instance_id,
                        platform=platform,
                        public_key=canonical_key,
                        credential_id=credential_id,
                    ),
                )
                existing_device = (
                    await self._session.execute(
                        select(AccountDevice)
                        .where(
                            AccountDevice.app_instance_id == app_instance_id
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if existing_device is not None and (
                    existing_device.account_id != account.id
                    or existing_device.status != "active"
                    or existing_device.revoked_at is not None
                    or existing_device.platform != platform
                    or not hmac.compare_digest(
                        existing_device.public_key, canonical_key
                    )
                    or not hmac.compare_digest(
                        existing_device.public_key_fingerprint,
                        hashlib.sha256(canonical_key).digest(),
                    )
                ):
                    raise InvalidAuthenticationResponse("authentication unavailable")
                try:
                    async with self._session.begin_nested():
                        issued = (
                            await session_service.register_device_and_issue_session(
                                RegisterDeviceAndIssueSession(
                                    account_id=account.id,
                                    app_instance_id=app_instance_id,
                                    platform=platform,
                                    display_name=challenge.device_display_name,
                                    public_key=canonical_key,
                                    now=now,
                                )
                            )
                        )
                        if verified.new_sign_count > identity.sign_count:
                            identity.sign_count = verified.new_sign_count
                        identity.passkey_backup_state = (
                            verified.credential_backed_up
                        )
                        identity.passkey_last_used_at = now
                        identity.updated_at = now
                        challenge.status = "consumed"
                        challenge.consumed_at = now
                        challenge.updated_at = now
                        await self._session.flush()
                except IntegrityError:
                    challenge = await self._lock_challenge(challenge_id)
                    return await self._reject(challenge, now)
                return AuthenticationVerified(account.id, issued)
            except (
                AccountSessionServiceError,
                InvalidAuthenticationResponse,
                InvalidSignature,
                ValueError,
                TypeError,
            ):
                return await self._reject(challenge, now)

    async def list_passkeys(
        self, account_id: UUID, now: datetime
    ) -> tuple[PasskeySummary, ...]:
        self._uuid("account_id", account_id)
        self._aware(now)
        account = await self._session.get(Account, account_id)
        if account is None or account.status != "active" or account.deleted_at is not None:
            raise AccountPasskeyUnavailable("passkey operation is unavailable")
        rows = list(
            (
                await self._session.execute(
                    select(AccountIdentity)
                    .where(
                        AccountIdentity.account_id == account_id,
                        AccountIdentity.identity_type == "passkey",
                        AccountIdentity.deleted_at.is_(None),
                    )
                    .order_by(AccountIdentity.created_at, AccountIdentity.id)
                )
            ).scalars()
        )
        return tuple(
            PasskeySummary(
                identity_id=row.id,
                display_name=row.passkey_display_name,
                transports=tuple(row.passkey_transports or ()),
                backup_eligible=bool(row.passkey_backup_eligible),
                backup_state=bool(row.passkey_backup_state),
                created_at=row.created_at,
                last_used_at=row.passkey_last_used_at,
                status="active" if row.status == "verified" else "revoked",
                revoked_at=row.passkey_revoked_at,
            )
            for row in rows
        )

    async def revoke_passkey(
        self, account_id: UUID, identity_id: UUID, now: datetime
    ) -> bool:
        self._uuid("account_id", account_id)
        self._uuid("identity_id", identity_id)
        self._aware(now)
        async with self._session.begin_nested():
            identity = (
                await self._session.execute(
                    select(AccountIdentity)
                    .where(
                        AccountIdentity.id == identity_id,
                        AccountIdentity.account_id == account_id,
                        AccountIdentity.identity_type == "passkey",
                        AccountIdentity.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if identity is None:
                raise AccountPasskeyUnavailable("passkey operation is unavailable")
            if identity.status == "verified":
                identity.status = "disabled"
                identity.passkey_revoked_at = now
                identity.passkey_revoked_reason = "owner_revoked"
                identity.updated_at = now
                await self._session.flush()
                return True
            return False

    async def _authenticated_context(
        self,
        account_id: UUID,
        session_id: UUID,
        now: datetime,
        *,
        lock: bool,
    ) -> tuple[Account, AccountSession, AccountDevice]:
        statement = select(Account).where(Account.id == account_id)
        if lock:
            statement = statement.with_for_update()
        account = (await self._session.execute(statement)).scalar_one_or_none()
        session_statement = select(AccountSession).where(
            AccountSession.id == session_id
        )
        device_statement = select(AccountDevice).join(
            AccountSession,
            AccountSession.device_id == AccountDevice.id,
        ).where(AccountSession.id == session_id)
        if lock:
            session_statement = session_statement.with_for_update()
            device_statement = device_statement.with_for_update()
        account_session = (
            await self._session.execute(session_statement)
        ).scalar_one_or_none()
        device = (
            await self._session.execute(device_statement)
        ).scalar_one_or_none()
        if (
            account is None
            or account.status != "active"
            or account.deleted_at is not None
            or account_session is None
            or account_session.account_id != account.id
            or account_session.status != "active"
            or account_session.security_version != account.security_version
            or now >= account_session.idle_expires_at
            or now >= account_session.absolute_expires_at
            or device is None
            or device.account_id != account.id
            or device.status != "active"
            or device.revoked_at is not None
        ):
            raise AccountPasskeyUnavailable("passkey operation is unavailable")
        return account, account_session, device

    async def _lock_challenge(
        self, challenge_id: UUID
    ) -> AccountWebAuthnChallenge | None:
        return (
            await self._session.execute(
                select(AccountWebAuthnChallenge)
                .where(AccountWebAuthnChallenge.id == challenge_id)
                .with_for_update()
            )
        ).scalar_one_or_none()

    def _challenge_available(
        self,
        challenge: AccountWebAuthnChallenge | None,
        ceremony_type: str,
        now: datetime,
    ) -> bool:
        if challenge is None:
            return False
        if (
            challenge.ceremony_type != ceremony_type
            or challenge.status != "pending"
            or challenge.attempts >= self._max_attempts
        ):
            return False
        if challenge.expires_at <= now:
            challenge.status = "expired"
            challenge.updated_at = now
            return False
        return True

    async def _reject(
        self,
        challenge: AccountWebAuthnChallenge | None,
        now: datetime,
    ) -> PasskeyRejected:
        if challenge is None:
            return PasskeyRejected(self._max_attempts)
        if challenge.status == "pending":
            challenge.attempts += 1
            challenge.updated_at = now
            if challenge.attempts >= self._max_attempts:
                challenge.status = "blocked"
            await self._session.flush()
        return PasskeyRejected(challenge.attempts)

    @staticmethod
    def _device_context_digest(
        app_instance_id: UUID, platform: str, public_key: bytes
    ) -> bytes:
        return hashlib.sha256(
            b"".join(
                _field(value)
                for value in (
                    b"restos-passkey-device-context-v1",
                    app_instance_id.bytes,
                    platform.encode("ascii"),
                    hashlib.sha256(public_key).digest(),
                )
            )
        ).digest()

    @staticmethod
    def _verify_device_signature(
        *, public_key: bytes, signature: bytes, message: bytes
    ) -> None:
        key = serialization.load_der_public_key(public_key)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("authentication unavailable")
        r, s = decode_dss_signature(signature)
        if encode_dss_signature(r, s) != signature:
            raise ValueError("authentication unavailable")
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))

    @staticmethod
    def _device_public_key(value: bytes) -> bytes:
        if not isinstance(value, bytes) or not value:
            raise InvalidAccountPasskeyRequest("device public key is invalid")
        try:
            key = serialization.load_der_public_key(value)
            if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
                key.curve, ec.SECP256R1
            ):
                raise ValueError
            return key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except (TypeError, ValueError) as error:
            raise InvalidAccountPasskeyRequest(
                "device public key is invalid"
            ) from error

    @staticmethod
    def _transports(values: list[Any] | None) -> tuple[str, ...]:
        normalized = tuple(
            sorted(
                {
                    value.value if hasattr(value, "value") else str(value)
                    for value in (values or ())
                }
            )
        )
        if any(value not in _ALLOWED_TRANSPORTS for value in normalized):
            raise InvalidRegistrationResponse("transport unavailable")
        return normalized

    @staticmethod
    def _display_name(value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidAccountPasskeyRequest("display name is invalid")
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > _MAX_DISPLAY_NAME:
            raise InvalidAccountPasskeyRequest("display name is invalid")
        return normalized

    @staticmethod
    def _platform(value: str) -> str:
        if not isinstance(value, str) or value not in _PLATFORMS:
            raise InvalidAccountPasskeyRequest("platform is invalid")
        return value

    @staticmethod
    def _uuid(name: str, value: UUID) -> None:
        if not isinstance(value, UUID):
            raise InvalidAccountPasskeyRequest(f"{name} must be a UUID")

    @staticmethod
    def _aware(value: datetime) -> None:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise InvalidAccountPasskeyRequest("timestamp is invalid")
