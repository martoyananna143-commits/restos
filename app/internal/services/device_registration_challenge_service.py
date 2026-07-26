"""One-time ES256 proof-of-possession challenges for device registration.

Public keys use canonical DER SubjectPublicKeyInfo. Signatures use ASN.1 DER
ECDSA over SHA-256. The signed message is a versioned, length-prefixed binary
encoding so field boundaries cannot be interpreted ambiguously.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import re
import secrets
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.device_registration_challenge import (
    DeviceRegistrationChallenge,
)
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import Invitation
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.internal.services.phone_verification_service import PhoneVerificationService


_SIX_ASCII_DIGITS = re.compile(r"^[0-9]{6}$")
_PLATFORMS = {"ios", "android", "web", "desktop", "unknown"}
_PROTOCOL = b"restos-device-registration-v1"


class DeviceRegistrationChallengeError(Exception):
    """Base controlled device challenge error."""


class InvalidDeviceRegistrationChallengeRequest(DeviceRegistrationChallengeError):
    """Runtime input is malformed."""


class DeviceRegistrationChallengeUnavailable(DeviceRegistrationChallengeError):
    """The context or proof is unavailable without disclosing which part failed."""


@dataclass(frozen=True)
class IssueDeviceRegistrationChallenge:
    invitation_code: str
    phone_verification_challenge_id: UUID
    phone: str
    app_instance_id: UUID
    platform: str
    public_key: bytes
    now: datetime


@dataclass(frozen=True)
class IssuedDeviceRegistrationChallenge:
    device_challenge_id: UUID
    invitation_id: UUID
    nonce: str
    algorithm: str
    expires_at: datetime


def _field(value: bytes) -> bytes:
    return len(value).to_bytes(4, "big") + value


def canonical_signed_message(
    *,
    device_challenge_id: UUID,
    invitation_id: UUID,
    phone_challenge_id: UUID,
    app_instance_id: UUID,
    platform: str,
    nonce: bytes,
) -> bytes:
    """Return the exact ES256 message: protocol plus six length-prefixed fields."""

    return b"".join(
        _field(value)
        for value in (
            _PROTOCOL,
            device_challenge_id.bytes,
            invitation_id.bytes,
            phone_challenge_id.bytes,
            app_instance_id.bytes,
            platform.encode("ascii"),
            nonce,
        )
    )


class DeviceRegistrationChallengeService:
    def __init__(
        self,
        session: AsyncSession,
        invitation_pepper: bytes,
        phone_pepper: bytes,
        ttl: timedelta = timedelta(minutes=5),
    ):
        if not isinstance(invitation_pepper, bytes) or len(invitation_pepper) < 32:
            raise ValueError("invitation pepper must contain at least 32 bytes")
        if not isinstance(phone_pepper, bytes) or len(phone_pepper) < 32:
            raise ValueError("phone pepper must contain at least 32 bytes")
        if ttl <= timedelta(0):
            raise ValueError("challenge TTL must be positive")
        self._session = session
        self._invitation_pepper = invitation_pepper
        self._phone_pepper = phone_pepper
        self._ttl = ttl

    async def issue_challenge(
        self, request: IssueDeviceRegistrationChallenge
    ) -> IssuedDeviceRegistrationChallenge:
        normalized_phone, canonical_key = self._validate_issue(request)
        invitation_digest = hmac.new(
            self._invitation_pepper,
            request.invitation_code.encode("ascii"),
            hashlib.sha256,
        ).digest()
        phone_digest = hmac.new(
            self._phone_pepper,
            normalized_phone.encode("ascii"),
            hashlib.sha256,
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
            if invitation is None:
                raise DeviceRegistrationChallengeUnavailable("challenge unavailable")
            profile = (
                await self._session.execute(
                    select(EmployeeProfile)
                    .where(EmployeeProfile.id == invitation.employee_profile_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                invitation.expires_at <= request.now
                or phone_challenge is None
                or phone_challenge.purpose != "invitation_registration"
                or phone_challenge.status != "verified"
                or phone_challenge.consumed_at is not None
                or phone_challenge.expires_at <= request.now
                or phone_challenge.invitation_id != invitation.id
                or phone_challenge.employee_profile_id != invitation.employee_profile_id
                or not hmac.compare_digest(phone_challenge.phone_digest, phone_digest)
                or profile is None
                or profile.deleted_at is not None
                or profile.employment_status != "invited"
                or profile.account_id is not None
                or profile.phone is None
            ):
                raise DeviceRegistrationChallengeUnavailable("challenge unavailable")
            try:
                profile_phone = PhoneVerificationService.normalize_e164(profile.phone)
            except Exception as error:
                raise DeviceRegistrationChallengeUnavailable(
                    "challenge unavailable"
                ) from error
            if not hmac.compare_digest(
                profile_phone.encode("ascii"), normalized_phone.encode("ascii")
            ):
                raise DeviceRegistrationChallengeUnavailable("challenge unavailable")

            pending = (
                await self._session.execute(
                    select(DeviceRegistrationChallenge)
                    .where(
                        DeviceRegistrationChallenge.invitation_id == invitation.id,
                        DeviceRegistrationChallenge.app_instance_id
                        == request.app_instance_id,
                        DeviceRegistrationChallenge.status == "pending",
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if pending is not None:
                if pending.expires_at > request.now:
                    raise DeviceRegistrationChallengeUnavailable("challenge unavailable")
                pending.status = "expired"
                pending.updated_at = request.now
                await self._session.flush()

            challenge_id = uuid4()
            nonce = secrets.token_bytes(32)
            expires_at = request.now + self._ttl
            challenge = DeviceRegistrationChallenge(
                id=challenge_id,
                invitation_id=invitation.id,
                phone_verification_challenge_id=phone_challenge.id,
                employee_profile_id=invitation.employee_profile_id,
                app_instance_id=request.app_instance_id,
                platform=request.platform,
                public_key=canonical_key,
                public_key_fingerprint=hashlib.sha256(canonical_key).digest(),
                nonce_digest=self._nonce_digest(
                    challenge_id,
                    invitation.id,
                    phone_challenge.id,
                    request.app_instance_id,
                    request.platform,
                    nonce,
                ),
                status="pending",
                expires_at=expires_at,
                consumed_at=None,
                created_at=request.now,
                updated_at=request.now,
            )
            self._session.add(challenge)
            await self._session.flush()
            return IssuedDeviceRegistrationChallenge(
                device_challenge_id=challenge_id,
                invitation_id=invitation.id,
                nonce=base64.urlsafe_b64encode(nonce).rstrip(b"=").decode("ascii"),
                algorithm="ES256",
                expires_at=expires_at,
            )

    async def verify_locked(
        self,
        *,
        device_challenge_id: UUID,
        nonce: bytes,
        signature: bytes,
        invitation_id: UUID,
        phone_challenge_id: UUID,
        employee_profile_id: UUID,
        app_instance_id: UUID,
        platform: str,
        now: datetime,
    ) -> DeviceRegistrationChallenge:
        challenge = (
            await self._session.execute(
                select(DeviceRegistrationChallenge)
                .where(DeviceRegistrationChallenge.id == device_challenge_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if (
            challenge is None
            or challenge.status != "pending"
            or challenge.expires_at <= now
            or challenge.invitation_id != invitation_id
            or challenge.phone_verification_challenge_id != phone_challenge_id
            or challenge.employee_profile_id != employee_profile_id
            or challenge.app_instance_id != app_instance_id
            or challenge.platform != platform
            or not hmac.compare_digest(
                challenge.nonce_digest,
                self._nonce_digest(
                    device_challenge_id,
                    invitation_id,
                    phone_challenge_id,
                    app_instance_id,
                    platform,
                    nonce,
                ),
            )
        ):
            raise DeviceRegistrationChallengeUnavailable("challenge unavailable")
        try:
            key = serialization.load_der_public_key(challenge.public_key)
            assert isinstance(key, ec.EllipticCurvePublicKey)
            key.verify(
                signature,
                canonical_signed_message(
                    device_challenge_id=device_challenge_id,
                    invitation_id=invitation_id,
                    phone_challenge_id=phone_challenge_id,
                    app_instance_id=app_instance_id,
                    platform=platform,
                    nonce=nonce,
                ),
                ec.ECDSA(hashes.SHA256()),
            )
        except (ValueError, TypeError, AssertionError, InvalidSignature) as error:
            raise DeviceRegistrationChallengeUnavailable(
                "challenge unavailable"
            ) from error
        return challenge

    def _validate_issue(
        self, request: IssueDeviceRegistrationChallenge
    ) -> tuple[str, bytes]:
        if not isinstance(request.invitation_code, str) or not _SIX_ASCII_DIGITS.fullmatch(
            request.invitation_code
        ):
            raise InvalidDeviceRegistrationChallengeRequest("invalid invitation code")
        if not isinstance(request.phone_verification_challenge_id, UUID) or not isinstance(
            request.app_instance_id, UUID
        ):
            raise InvalidDeviceRegistrationChallengeRequest("invalid identifier")
        if not isinstance(request.platform, str) or request.platform not in _PLATFORMS:
            raise InvalidDeviceRegistrationChallengeRequest("invalid platform")
        if not isinstance(request.public_key, bytes) or not request.public_key:
            raise InvalidDeviceRegistrationChallengeRequest("invalid public key")
        if (
            not isinstance(request.now, datetime)
            or request.now.tzinfo is None
            or request.now.utcoffset() is None
        ):
            raise InvalidDeviceRegistrationChallengeRequest("invalid timestamp")
        try:
            normalized_phone = PhoneVerificationService.normalize_e164(request.phone)
            key = serialization.load_der_public_key(request.public_key)
            if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
                key.curve, ec.SECP256R1
            ):
                raise ValueError
            canonical_key = key.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception as error:
            raise InvalidDeviceRegistrationChallengeRequest(
                "invalid challenge input"
            ) from error
        return normalized_phone, canonical_key

    @staticmethod
    def _nonce_digest(
        challenge_id: UUID,
        invitation_id: UUID,
        phone_challenge_id: UUID,
        app_instance_id: UUID,
        platform: str,
        nonce: bytes,
    ) -> bytes:
        return hashlib.sha256(
            canonical_signed_message(
                device_challenge_id=challenge_id,
                invitation_id=invitation_id,
                phone_challenge_id=phone_challenge_id,
                app_instance_id=app_instance_id,
                platform=platform,
                nonce=nonce,
            )
        ).digest()
