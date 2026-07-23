"""Isolated device registration and rotating refresh-session service."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import re
import secrets
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.account import Account, AccountDevice, AccountSession


_PLATFORMS = {"ios", "android", "web", "desktop", "unknown"}
_TOKEN_PATTERN = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\.([A-Za-z0-9_-]+)$")
_MAX_DISPLAY_NAME = 255
_MAX_SECURITY_VERSION = 2_147_483_647


class AccountSessionServiceError(Exception):
    """Base controlled account-session error."""


class InvalidAccountSessionRequest(AccountSessionServiceError):
    """Registration or revocation input is invalid."""


class AccountUnavailableForSession(AccountSessionServiceError):
    """Account cannot issue or manage sessions."""


class DeviceIdentityMismatch(AccountSessionServiceError):
    """An app instance was presented with a different public key."""


class DeviceUnavailableForSession(AccountSessionServiceError):
    """Device is revoked, disabled, missing, or belongs to another account."""


class InvalidRefreshSession(AccountSessionServiceError):
    """Refresh token is malformed, unknown, or has an invalid secret."""


class SecurityVersionExhausted(AccountSessionServiceError):
    """Account security version cannot be increased safely."""


@dataclass(frozen=True)
class RegisterDeviceAndIssueSession:
    account_id: UUID
    app_instance_id: UUID
    platform: str
    display_name: str | None
    public_key: bytes
    now: datetime


@dataclass(frozen=True)
class IssuedDeviceSession:
    account_id: UUID
    device_id: UUID
    session_id: UUID
    refresh_token: str
    refresh_family: UUID
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True)
class RotateRefreshSession:
    refresh_token: str
    now: datetime


@dataclass(frozen=True)
class RotatedRefreshSession:
    account_id: UUID
    device_id: UUID
    session_id: UUID
    previous_session_id: UUID
    refresh_token: str
    refresh_family: UUID
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True)
class RefreshRejected:
    reason: str
    requires_full_login: bool = True


@dataclass(frozen=True)
class RevokeDeviceSessions:
    actor_account_id: UUID
    target_account_id: UUID
    device_id: UUID
    now: datetime
    reason: str


@dataclass(frozen=True)
class RevokedDeviceSessions:
    device_id: UUID
    revoked_session_count: int


@dataclass(frozen=True)
class RevokeAllAccountSessions:
    account_id: UUID
    now: datetime


@dataclass(frozen=True)
class RevokedAllAccountSessions:
    account_id: UUID
    security_version: int
    revoked_session_count: int


class AccountSessionService:
    """Manage additive AccountDevice and AccountSession records."""

    def __init__(
        self,
        session: AsyncSession,
        pepper: bytes,
        selector_generator: Callable[[], UUID] | None = None,
        secret_generator: Callable[[], bytes] | None = None,
        idle_ttl: timedelta = timedelta(days=30),
        absolute_ttl: timedelta = timedelta(days=90),
    ):
        if not isinstance(pepper, bytes) or len(pepper) < 32:
            raise ValueError("session pepper must contain at least 32 bytes")
        if idle_ttl <= timedelta(0) or absolute_ttl <= timedelta(0):
            raise ValueError("session TTL values must be positive")
        if idle_ttl > absolute_ttl:
            raise ValueError("idle TTL must not exceed absolute TTL")
        self._session = session
        self._pepper = pepper
        self._selector_generator = selector_generator or uuid4
        self._secret_generator = secret_generator or (lambda: secrets.token_bytes(32))
        self._idle_ttl = idle_ttl
        self._absolute_ttl = absolute_ttl

    async def register_device_and_issue_session(
        self, request: RegisterDeviceAndIssueSession
    ) -> IssuedDeviceSession:
        self._validate_registration(request)
        async with self._session.begin_nested():
            account = await self._active_account(request.account_id, lock=True)
            if account is None:
                raise AccountUnavailableForSession("account is unavailable")
            fingerprint = hashlib.sha256(request.public_key).digest()
            device = (
                await self._session.execute(
                    select(AccountDevice)
                    .where(
                        AccountDevice.account_id == request.account_id,
                        AccountDevice.app_instance_id == request.app_instance_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if device is None:
                device = AccountDevice(
                    id=uuid4(),
                    account_id=request.account_id,
                    app_instance_id=request.app_instance_id,
                    platform=request.platform,
                    display_name=request.display_name,
                    public_key=request.public_key,
                    public_key_fingerprint=fingerprint,
                    quick_unlock_enabled=False,
                    status="active",
                    last_seen_at=request.now,
                    revoked_at=None,
                    revoked_reason=None,
                    created_at=request.now,
                    updated_at=request.now,
                )
                self._session.add(device)
                await self._session.flush()
            else:
                if device.status != "active":
                    raise DeviceUnavailableForSession("device is unavailable")
                if not hmac.compare_digest(device.public_key, request.public_key) or not hmac.compare_digest(
                    device.public_key_fingerprint, fingerprint
                ):
                    raise DeviceIdentityMismatch("device public key does not match")
                device.last_seen_at = request.now
                device.updated_at = request.now
            return await self._issue_first_session(account, device, request.now)

    async def rotate_refresh_session(
        self, request: RotateRefreshSession
    ) -> RotatedRefreshSession | RefreshRejected:
        self._require_aware("now", request.now)
        selector, secret = self._parse_refresh_token(request.refresh_token)
        async with self._session.begin_nested():
            old = (
                await self._session.execute(
                    select(AccountSession)
                    .where(AccountSession.token_selector == selector)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if old is None:
                raise InvalidRefreshSession("refresh session is unavailable")
            digest = self._refresh_digest(selector, secret)
            if not hmac.compare_digest(old.refresh_secret_digest, digest):
                raise InvalidRefreshSession("refresh session is unavailable")
            if old.status == "rotated":
                active_family = list(
                    (
                        await self._session.execute(
                            select(AccountSession)
                            .where(
                                AccountSession.refresh_family == old.refresh_family,
                                AccountSession.status == "active",
                            )
                            .with_for_update()
                        )
                    ).scalars()
                )
                for session in active_family:
                    session.status = "compromised"
                    session.revoked_at = request.now
                    session.revoked_reason = "refresh_token_reuse"
                    session.updated_at = request.now
                await self._session.flush()
                return RefreshRejected(reason="refresh_token_reuse")
            if old.status != "active":
                return RefreshRejected(reason=old.status)

            account = await self._active_account(old.account_id, lock=True)
            if account is None:
                return RefreshRejected(reason="account_unavailable")
            device = (
                await self._session.execute(
                    select(AccountDevice)
                    .where(
                        AccountDevice.id == old.device_id,
                        AccountDevice.account_id == old.account_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if device is None or device.status != "active":
                return RefreshRejected(reason="device_unavailable")
            if old.security_version != account.security_version:
                return RefreshRejected(reason="security_version_changed")
            if request.now >= old.idle_expires_at or request.now >= old.absolute_expires_at:
                old.status = "expired"
                old.updated_at = request.now
                await self._session.flush()
                return RefreshRejected(reason="expired")

            old.status = "rotated"
            old.last_used_at = request.now
            old.updated_at = request.now
            selector_new, secret_new, token_new = self._new_refresh_token()
            idle_expires_at = min(
                request.now + self._idle_ttl, old.absolute_expires_at
            )
            if idle_expires_at <= request.now:
                old.status = "expired"
                await self._session.flush()
                return RefreshRejected(reason="expired")
            new_session = AccountSession(
                id=uuid4(),
                account_id=old.account_id,
                device_id=old.device_id,
                token_selector=selector_new,
                refresh_secret_digest=self._refresh_digest(selector_new, secret_new),
                refresh_family=old.refresh_family,
                previous_rotated_session_id=old.id,
                security_version=account.security_version,
                status="active",
                issued_at=request.now,
                last_used_at=None,
                idle_expires_at=idle_expires_at,
                absolute_expires_at=old.absolute_expires_at,
                revoked_at=None,
                revoked_reason=None,
                created_at=request.now,
                updated_at=request.now,
            )
            self._session.add(new_session)
            device.last_seen_at = request.now
            device.updated_at = request.now
            await self._session.flush()
            return RotatedRefreshSession(
                account_id=old.account_id,
                device_id=old.device_id,
                session_id=new_session.id,
                previous_session_id=old.id,
                refresh_token=token_new,
                refresh_family=old.refresh_family,
                idle_expires_at=idle_expires_at,
                absolute_expires_at=old.absolute_expires_at,
            )

    async def revoke_device_sessions(
        self, request: RevokeDeviceSessions
    ) -> RevokedDeviceSessions:
        if not isinstance(request.actor_account_id, UUID):
            raise InvalidAccountSessionRequest("actor_account_id must be a UUID")
        if not isinstance(request.target_account_id, UUID):
            raise InvalidAccountSessionRequest("target_account_id must be a UUID")
        if not isinstance(request.device_id, UUID):
            raise InvalidAccountSessionRequest("device_id must be a UUID")
        self._require_aware("now", request.now)
        if not isinstance(request.reason, str):
            raise InvalidAccountSessionRequest("revocation reason must be a string")
        reason = request.reason.strip()
        if not reason or len(reason) > 500:
            raise InvalidAccountSessionRequest("revocation reason is invalid")
        if request.actor_account_id != request.target_account_id:
            raise DeviceUnavailableForSession("only an own device may be revoked")
        async with self._session.begin_nested():
            device = (
                await self._session.execute(
                    select(AccountDevice)
                    .where(
                        AccountDevice.id == request.device_id,
                        AccountDevice.account_id == request.target_account_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if device is None:
                raise DeviceUnavailableForSession("device is unavailable")
            if device.status == "disabled":
                raise DeviceUnavailableForSession("device is unavailable")
            if device.status != "revoked":
                device.status = "revoked"
                device.revoked_at = request.now
                device.revoked_reason = reason
                device.updated_at = request.now
            device.quick_unlock_enabled = False
            active_sessions = list(
                (
                    await self._session.execute(
                        select(AccountSession)
                        .where(
                            AccountSession.device_id == device.id,
                            AccountSession.account_id == request.target_account_id,
                            AccountSession.status == "active",
                        )
                        .with_for_update()
                    )
                ).scalars()
            )
            for session in active_sessions:
                session.status = "revoked"
                session.revoked_at = request.now
                session.revoked_reason = "device_revoked"
                session.updated_at = request.now
            await self._session.flush()
            return RevokedDeviceSessions(device.id, len(active_sessions))

    async def revoke_all_account_sessions(
        self, request: RevokeAllAccountSessions
    ) -> RevokedAllAccountSessions:
        if not isinstance(request.account_id, UUID):
            raise InvalidAccountSessionRequest("account_id must be a UUID")
        self._require_aware("now", request.now)
        async with self._session.begin_nested():
            account = (
                await self._session.execute(
                    select(Account)
                    .where(Account.id == request.account_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if account is None or account.deleted_at is not None:
                raise AccountUnavailableForSession("account is unavailable")
            if account.security_version >= _MAX_SECURITY_VERSION:
                raise SecurityVersionExhausted("security version is exhausted")
            account.security_version += 1
            account.updated_at = request.now
            active_sessions = list(
                (
                    await self._session.execute(
                        select(AccountSession)
                        .where(
                            AccountSession.account_id == request.account_id,
                            AccountSession.status == "active",
                        )
                        .with_for_update()
                    )
                ).scalars()
            )
            for session in active_sessions:
                session.status = "revoked"
                session.revoked_at = request.now
                session.revoked_reason = "all_sessions_revoked"
                session.updated_at = request.now
            devices = list(
                (
                    await self._session.execute(
                        select(AccountDevice)
                        .where(AccountDevice.account_id == request.account_id)
                        .with_for_update()
                    )
                ).scalars()
            )
            for device in devices:
                device.quick_unlock_enabled = False
                device.updated_at = request.now
            await self._session.flush()
            return RevokedAllAccountSessions(
                account.id, account.security_version, len(active_sessions)
            )

    async def _issue_first_session(
        self, account: Account, device: AccountDevice, now: datetime
    ) -> IssuedDeviceSession:
        selector, secret, token = self._new_refresh_token()
        absolute_expires_at = now + self._absolute_ttl
        idle_expires_at = min(now + self._idle_ttl, absolute_expires_at)
        family = uuid4()
        session = AccountSession(
            id=uuid4(), account_id=account.id, device_id=device.id,
            token_selector=selector,
            refresh_secret_digest=self._refresh_digest(selector, secret),
            refresh_family=family, previous_rotated_session_id=None,
            security_version=account.security_version, status="active",
            issued_at=now, last_used_at=None,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            revoked_at=None, revoked_reason=None,
            created_at=now, updated_at=now,
        )
        self._session.add(session)
        await self._session.flush()
        return IssuedDeviceSession(
            account.id, device.id, session.id, token, family,
            idle_expires_at, absolute_expires_at,
        )

    async def _active_account(self, account_id: UUID, lock: bool) -> Account | None:
        statement = select(Account).where(
            Account.id == account_id,
            Account.status == "active",
            Account.deleted_at.is_(None),
        )
        if lock:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    def _new_refresh_token(self) -> tuple[UUID, bytes, str]:
        selector = self._selector_generator()
        secret = self._secret_generator()
        if not isinstance(selector, UUID):
            raise InvalidAccountSessionRequest("selector generator must return UUID")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise InvalidAccountSessionRequest(
                "secret generator must return at least 32 bytes"
            )
        encoded = base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")
        return selector, secret, f"{selector}.{encoded}"

    def _parse_refresh_token(self, token: str) -> tuple[UUID, bytes]:
        if not isinstance(token, str):
            raise InvalidRefreshSession("refresh session is unavailable")
        match = _TOKEN_PATTERN.fullmatch(token)
        if match is None:
            raise InvalidRefreshSession("refresh session is unavailable")
        try:
            selector = UUID(match.group(1))
            encoded = match.group(2)
            secret = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (ValueError, TypeError):
            raise InvalidRefreshSession("refresh session is unavailable") from None
        if len(secret) < 32:
            raise InvalidRefreshSession("refresh session is unavailable")
        return selector, secret

    def _refresh_digest(self, selector: UUID, secret: bytes) -> bytes:
        return hmac.new(
            self._pepper, selector.bytes + secret, hashlib.sha256
        ).digest()

    def _validate_registration(self, request: RegisterDeviceAndIssueSession) -> None:
        if not isinstance(request.account_id, UUID) or not isinstance(
            request.app_instance_id, UUID
        ):
            raise InvalidAccountSessionRequest("account and app instance must be UUID")
        if not isinstance(request.platform, str) or request.platform not in _PLATFORMS:
            raise InvalidAccountSessionRequest("unsupported platform")
        if request.display_name is not None and not isinstance(
            request.display_name, str
        ):
            raise InvalidAccountSessionRequest("display_name is invalid")
        if request.display_name is not None and len(
            request.display_name
        ) > _MAX_DISPLAY_NAME:
            raise InvalidAccountSessionRequest("display_name is invalid")
        if not isinstance(request.public_key, bytes) or not request.public_key:
            raise InvalidAccountSessionRequest("public_key must not be empty")
        self._require_aware("now", request.now)

    @staticmethod
    def _require_aware(name: str, value: datetime) -> None:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise InvalidAccountSessionRequest(f"{name} must be timezone-aware")
