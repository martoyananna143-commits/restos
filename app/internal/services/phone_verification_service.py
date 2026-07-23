"""Provider-neutral SMS phone verification challenge service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import re
import secrets
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.account import Account
from app.infra.database.models.employee_profile import EmployeeProfile
from app.infra.database.models.invitation_v1 import Invitation
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)


_PURPOSES = {"invitation_registration", "login", "password_reset", "phone_change"}
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$")
_SIX_ASCII_DIGITS = re.compile(r"^[0-9]{6}$")


class SmsVerificationSender(Protocol):
    async def send_verification_code(
        self,
        phone: str,
        code: str,
        purpose: str,
        expires_in_seconds: int,
        autofill_domain: str,
    ) -> None: ...


class PhoneVerificationError(Exception):
    """Base controlled phone-verification error."""


class InvalidPhoneVerificationRequest(PhoneVerificationError):
    """Request types, phone, purpose, or configuration are invalid."""


class PhoneVerificationUnavailable(PhoneVerificationError):
    """Related context is unavailable without revealing which object failed."""


class PhoneVerificationCooldown(PhoneVerificationError):
    """A pending challenge cannot be resent yet."""


class InvalidOrUnavailablePhoneChallenge(PhoneVerificationError):
    """Challenge is unknown, terminal, or does not match its phone."""


class SmsDeliveryFailed(PhoneVerificationError):
    """SMS provider failed; the new challenge was rolled back."""


@dataclass(frozen=True)
class RequestPhoneVerificationCode:
    purpose: str
    phone: str
    now: datetime
    account_id: UUID | None = None
    invitation_id: UUID | None = None
    employee_profile_id: UUID | None = None


@dataclass(frozen=True)
class PhoneVerificationCodeRequested:
    challenge_id: UUID
    expires_at: datetime
    resend_available_at: datetime


@dataclass(frozen=True)
class VerifyPhoneVerificationCode:
    challenge_id: UUID
    phone: str
    code: str
    now: datetime


@dataclass(frozen=True)
class PhoneVerificationSucceeded:
    challenge_id: UUID
    purpose: str
    account_id: UUID | None
    invitation_id: UUID | None
    employee_profile_id: UUID | None
    verified_at: datetime


@dataclass(frozen=True)
class PhoneVerificationRejected:
    reason: str
    attempts_remaining: int


@dataclass(frozen=True)
class CancelPhoneVerificationChallenge:
    challenge_id: UUID
    now: datetime


class PhoneVerificationService:
    """Create, verify, and cancel SMS OTP challenges within caller transactions."""

    def __init__(
        self,
        session: AsyncSession,
        sender: SmsVerificationSender,
        phone_pepper: bytes,
        code_pepper: bytes,
        autofill_domain: str,
        code_generator: Callable[[], str] | None = None,
        code_ttl: timedelta = timedelta(minutes=5),
        resend_cooldown: timedelta = timedelta(seconds=60),
        max_attempts: int = 5,
    ):
        if not isinstance(phone_pepper, bytes) or len(phone_pepper) < 32:
            raise ValueError("phone pepper must contain at least 32 bytes")
        if not isinstance(code_pepper, bytes) or len(code_pepper) < 32:
            raise ValueError("code pepper must contain at least 32 bytes")
        if code_ttl <= timedelta(0) or resend_cooldown < timedelta(0):
            raise ValueError("verification timeouts are invalid")
        if not isinstance(max_attempts, int) or max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if not isinstance(autofill_domain, str) or not autofill_domain.strip():
            raise ValueError("autofill_domain is required")
        self._session = session
        self._sender = sender
        self._phone_pepper = phone_pepper
        self._code_pepper = code_pepper
        self._autofill_domain = autofill_domain.strip()
        self._code_generator = code_generator or (
            lambda: f"{secrets.randbelow(1_000_000):06d}"
        )
        self._code_ttl = code_ttl
        self._resend_cooldown = resend_cooldown
        self._max_attempts = max_attempts

    async def request_code(
        self, request: RequestPhoneVerificationCode
    ) -> PhoneVerificationCodeRequested:
        self._validate_request_types(request)
        phone = self.normalize_e164(request.phone)
        phone_digest = self._phone_digest(phone)
        try:
            async with self._session.begin_nested():
                await self._validate_context(request)
                pending = (
                    await self._session.execute(
                        select(PhoneVerificationChallenge)
                        .where(
                            PhoneVerificationChallenge.purpose == request.purpose,
                            PhoneVerificationChallenge.phone_digest == phone_digest,
                            PhoneVerificationChallenge.status == "pending",
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if pending is not None:
                    if pending.expires_at <= request.now:
                        pending.status = "expired"
                        pending.updated_at = request.now
                    elif request.now < pending.resend_available_at:
                        raise PhoneVerificationCooldown(
                            "verification resend is not available yet"
                        )
                    else:
                        pending.status = "cancelled"
                        pending.cancelled_at = request.now
                        pending.updated_at = request.now

                challenge_id = uuid4()
                code = self._code_generator()
                if not isinstance(code, str) or not _SIX_ASCII_DIGITS.fullmatch(code):
                    raise InvalidPhoneVerificationRequest(
                        "code generator must return six ASCII digits"
                    )
                expires_at = request.now + self._code_ttl
                resend_at = request.now + self._resend_cooldown
                challenge = PhoneVerificationChallenge(
                    id=challenge_id,
                    account_id=request.account_id,
                    invitation_id=request.invitation_id,
                    employee_profile_id=request.employee_profile_id,
                    purpose=request.purpose,
                    phone_digest=phone_digest,
                    code_digest=self._code_digest(
                        challenge_id, request.purpose, phone_digest, code
                    ),
                    status="pending",
                    attempts_used=0,
                    max_attempts=self._max_attempts,
                    expires_at=expires_at,
                    resend_available_at=resend_at,
                    verified_at=None,
                    locked_at=None,
                    cancelled_at=None,
                    created_at=request.now,
                    updated_at=request.now,
                )
                self._session.add(challenge)
                await self._session.flush()
                try:
                    await self._sender.send_verification_code(
                        phone=phone,
                        code=code,
                        purpose=request.purpose,
                        expires_in_seconds=int(self._code_ttl.total_seconds()),
                        autofill_domain=self._autofill_domain,
                    )
                except Exception as error:
                    raise SmsDeliveryFailed("SMS delivery failed") from error
                return PhoneVerificationCodeRequested(
                    challenge_id, expires_at, resend_at
                )
        except IntegrityError as error:
            if _postgres_constraint_name(error) == "uq_phone_verification_challenges_active_pending":
                raise PhoneVerificationCooldown(
                    "verification resend is not available yet"
                ) from error
            raise

    async def verify_code(
        self, request: VerifyPhoneVerificationCode
    ) -> PhoneVerificationSucceeded | PhoneVerificationRejected:
        if not isinstance(request.challenge_id, UUID):
            raise InvalidPhoneVerificationRequest("challenge_id must be a UUID")
        self._require_aware("now", request.now)
        phone = self.normalize_e164(request.phone)
        if not isinstance(request.code, str) or not _SIX_ASCII_DIGITS.fullmatch(
            request.code
        ):
            raise InvalidOrUnavailablePhoneChallenge("challenge is unavailable")
        phone_digest = self._phone_digest(phone)
        async with self._session.begin_nested():
            challenge = (
                await self._session.execute(
                    select(PhoneVerificationChallenge)
                    .where(PhoneVerificationChallenge.id == request.challenge_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if challenge is None or not hmac.compare_digest(
                challenge.phone_digest, phone_digest
            ):
                raise InvalidOrUnavailablePhoneChallenge("challenge is unavailable")
            if challenge.status != "pending":
                raise InvalidOrUnavailablePhoneChallenge("challenge is unavailable")
            if challenge.expires_at <= request.now:
                challenge.status = "expired"
                challenge.updated_at = request.now
                await self._session.flush()
                return PhoneVerificationRejected("expired", 0)
            if challenge.attempts_used >= challenge.max_attempts:
                challenge.status = "locked"
                challenge.locked_at = request.now
                challenge.updated_at = request.now
                await self._session.flush()
                return PhoneVerificationRejected("locked", 0)
            expected = self._code_digest(
                challenge.id,
                challenge.purpose,
                challenge.phone_digest,
                request.code,
            )
            if not hmac.compare_digest(challenge.code_digest, expected):
                challenge.attempts_used += 1
                remaining = challenge.max_attempts - challenge.attempts_used
                if remaining == 0:
                    challenge.status = "locked"
                    challenge.locked_at = request.now
                challenge.updated_at = request.now
                await self._session.flush()
                return PhoneVerificationRejected(
                    "locked" if remaining == 0 else "invalid_code", remaining
                )
            challenge.status = "verified"
            challenge.verified_at = request.now
            challenge.updated_at = request.now
            await self._session.flush()
            return PhoneVerificationSucceeded(
                challenge.id,
                challenge.purpose,
                challenge.account_id,
                challenge.invitation_id,
                challenge.employee_profile_id,
                request.now,
            )

    async def cancel_challenge(
        self, request: CancelPhoneVerificationChallenge
    ) -> None:
        if not isinstance(request.challenge_id, UUID):
            raise InvalidPhoneVerificationRequest("challenge_id must be a UUID")
        self._require_aware("now", request.now)
        async with self._session.begin_nested():
            challenge = (
                await self._session.execute(
                    select(PhoneVerificationChallenge)
                    .where(PhoneVerificationChallenge.id == request.challenge_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if challenge is None or challenge.status != "pending":
                raise InvalidOrUnavailablePhoneChallenge("challenge is unavailable")
            challenge.status = "cancelled"
            challenge.cancelled_at = request.now
            challenge.updated_at = request.now
            await self._session.flush()

    async def _validate_context(self, request: RequestPhoneVerificationCode) -> None:
        if request.purpose in {"login", "phone_change"}:
            account = (
                await self._session.execute(
                    select(Account.id).where(
                        Account.id == request.account_id,
                        Account.status == "active",
                        Account.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if account is None:
                raise PhoneVerificationUnavailable("verification is unavailable")
        elif request.purpose == "password_reset" and request.account_id is not None:
            account = (
                await self._session.execute(
                    select(Account.id).where(
                        Account.id == request.account_id,
                        Account.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if account is None:
                raise PhoneVerificationUnavailable("verification is unavailable")
        elif request.purpose == "invitation_registration":
            invitation = (
                await self._session.execute(
                    select(Invitation).where(
                        Invitation.id == request.invitation_id,
                        Invitation.employee_profile_id == request.employee_profile_id,
                        Invitation.status == "pending",
                        Invitation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            profile = (
                await self._session.execute(
                    select(EmployeeProfile.id).where(
                        EmployeeProfile.id == request.employee_profile_id,
                        EmployeeProfile.deleted_at.is_(None),
                        EmployeeProfile.employment_status == "invited",
                    )
                )
            ).scalar_one_or_none()
            if invitation is None or profile is None:
                raise PhoneVerificationUnavailable("verification is unavailable")

    def _validate_request_types(self, request: RequestPhoneVerificationCode) -> None:
        if not isinstance(request.purpose, str) or request.purpose not in _PURPOSES:
            raise InvalidPhoneVerificationRequest("purpose is invalid")
        self._require_aware("now", request.now)
        for name in ("account_id", "invitation_id", "employee_profile_id"):
            value = getattr(request, name)
            if value is not None and not isinstance(value, UUID):
                raise InvalidPhoneVerificationRequest(f"{name} must be a UUID")
        if request.purpose in {"login", "phone_change"} and request.account_id is None:
            raise InvalidPhoneVerificationRequest("account_id is required")
        if request.purpose == "invitation_registration" and (
            request.invitation_id is None or request.employee_profile_id is None
        ):
            raise InvalidPhoneVerificationRequest(
                "invitation and employee profile are required"
            )

    @staticmethod
    def normalize_e164(phone: str) -> str:
        if not isinstance(phone, str):
            raise InvalidPhoneVerificationRequest("phone must be a string")
        normalized = phone.strip()
        for character in " -()":
            normalized = normalized.replace(character, "")
        if not _E164.fullmatch(normalized):
            raise InvalidPhoneVerificationRequest("phone must be valid E.164")
        return normalized

    def _phone_digest(self, phone: str) -> bytes:
        return hmac.new(
            self._phone_pepper, phone.encode("ascii"), hashlib.sha256
        ).digest()

    def _code_digest(
        self, challenge_id: UUID, purpose: str, phone_digest: bytes, code: str
    ) -> bytes:
        material = (
            challenge_id.bytes
            + purpose.encode("ascii")
            + phone_digest
            + code.encode("ascii")
        )
        return hmac.new(self._code_pepper, material, hashlib.sha256).digest()

    @staticmethod
    def _require_aware(name: str, value: datetime) -> None:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise InvalidPhoneVerificationRequest(f"{name} must be timezone-aware")


def _postgres_constraint_name(error: IntegrityError) -> str | None:
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
