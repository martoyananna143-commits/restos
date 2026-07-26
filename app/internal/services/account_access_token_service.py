"""Short-lived Account access tokens with mandatory database revalidation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.database.models.account import Account, AccountDevice, AccountSession


_ALGORITHM = "HS256"
_ISSUER = "restos-account-auth"
_AUDIENCE = "restos-api"


class InvalidAccountAccessTokenRequest(Exception):
    """Token-service input is malformed."""


class AccountAccessTokenConfigurationError(Exception):
    """The access-token key or TTL is unavailable or unsafe."""


class AccountAccessTokenRejected(Exception):
    """A token or its backing Account session is unavailable."""


@dataclass(frozen=True)
class IssueAccountAccessToken:
    account_id: UUID
    session_id: UUID
    device_id: UUID
    now: datetime


@dataclass(frozen=True)
class IssuedAccountAccessToken:
    access_token: str
    expires_at: datetime


@dataclass(frozen=True)
class VerifyAccountAccessToken:
    access_token: str
    now: datetime


@dataclass(frozen=True)
class CurrentAccountPrincipal:
    account_id: UUID
    session_id: UUID
    device_id: UUID
    security_version: int
    token_expires_at: datetime


class AccountAccessTokenService:
    """Issue and verify access tokens without mutating database state."""

    def __init__(
        self,
        session: AsyncSession,
        key: bytes,
        ttl: timedelta = timedelta(seconds=600),
    ):
        if not isinstance(key, bytes) or len(key) < 32:
            raise AccountAccessTokenConfigurationError(
                "account access-token configuration is unavailable"
            )
        if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
            raise AccountAccessTokenConfigurationError(
                "account access-token configuration is unavailable"
            )
        self._session = session
        self._key = key
        self._ttl = ttl

    async def issue(
        self, request: IssueAccountAccessToken
    ) -> IssuedAccountAccessToken:
        self._uuid("account_id", request.account_id)
        self._uuid("session_id", request.session_id)
        self._uuid("device_id", request.device_id)
        self._aware("now", request.now)

        account, device, account_session = await self._load(
            request.account_id, request.device_id, request.session_id
        )
        self._eligible(account, device, account_session, request.now)
        expires_at = min(request.now + self._ttl, account_session.absolute_expires_at)
        if expires_at <= request.now:
            raise AccountAccessTokenRejected("authentication is unavailable")
        issued_at = int(request.now.timestamp())
        claims = {
            "sub": str(account.id),
            "sid": str(account_session.id),
            "did": str(device.id),
            "sv": account.security_version,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": int(expires_at.timestamp()),
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "typ": "access",
        }
        return IssuedAccountAccessToken(
            access_token=jwt.encode(claims, self._key, algorithm=_ALGORITHM),
            expires_at=expires_at,
        )

    async def verify(
        self, request: VerifyAccountAccessToken
    ) -> CurrentAccountPrincipal:
        if not isinstance(request.access_token, str) or not request.access_token:
            raise InvalidAccountAccessTokenRequest("access_token is required")
        self._aware("now", request.now)
        try:
            header = jwt.get_unverified_header(request.access_token)
            if header.get("alg") != _ALGORITHM:
                raise AccountAccessTokenRejected("authentication is unavailable")
            claims = jwt.decode(
                request.access_token,
                self._key,
                algorithms=[_ALGORITHM],
                issuer=_ISSUER,
                audience=_AUDIENCE,
                options={"require_exp": True, "require_iat": True, "require_nbf": True},
            )
        except AccountAccessTokenRejected:
            raise
        except JWTError as error:
            raise AccountAccessTokenRejected(
                "authentication is unavailable"
            ) from error
        try:
            if claims.get("typ") != "access":
                raise ValueError
            account_id = UUID(claims["sub"])
            session_id = UUID(claims["sid"])
            device_id = UUID(claims["did"])
            security_version = claims["sv"]
            if (
                isinstance(security_version, bool)
                or not isinstance(security_version, int)
                or security_version < 1
            ):
                raise ValueError
            timestamps = {
                name: claims[name] for name in ("iat", "nbf", "exp")
            }
            if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in timestamps.values()
            ):
                raise ValueError
            issued_at = datetime.fromtimestamp(timestamps["iat"], timezone.utc)
            not_before = datetime.fromtimestamp(timestamps["nbf"], timezone.utc)
            expires_at = datetime.fromtimestamp(timestamps["exp"], timezone.utc)
            if issued_at > request.now or not_before > request.now:
                raise ValueError
            if expires_at <= request.now:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise AccountAccessTokenRejected(
                "authentication is unavailable"
            ) from error

        account, device, account_session = await self._load(
            account_id, device_id, session_id
        )
        self._eligible(account, device, account_session, request.now)
        if account.security_version != security_version:
            raise AccountAccessTokenRejected("authentication is unavailable")
        return CurrentAccountPrincipal(
            account_id=account_id,
            session_id=session_id,
            device_id=device_id,
            security_version=security_version,
            token_expires_at=expires_at,
        )

    async def _load(
        self, account_id: UUID, device_id: UUID, session_id: UUID
    ) -> tuple[Account | None, AccountDevice | None, AccountSession | None]:
        account = await self._session.get(Account, account_id)
        device = await self._session.get(AccountDevice, device_id)
        account_session = await self._session.get(AccountSession, session_id)
        return account, device, account_session

    @staticmethod
    def _eligible(
        account: Account | None,
        device: AccountDevice | None,
        account_session: AccountSession | None,
        now: datetime,
    ) -> None:
        if (
            account is None
            or account.status != "active"
            or account.deleted_at is not None
            or device is None
            or device.account_id != account.id
            or device.status != "active"
            or device.revoked_at is not None
            or account_session is None
            or account_session.account_id != account.id
            or account_session.device_id != device.id
            or account_session.status != "active"
            or account_session.security_version != account.security_version
            or now >= account_session.idle_expires_at
            or now >= account_session.absolute_expires_at
        ):
            raise AccountAccessTokenRejected("authentication is unavailable")

    @staticmethod
    def _uuid(name: str, value: UUID) -> None:
        if not isinstance(value, UUID):
            raise InvalidAccountAccessTokenRequest(f"{name} must be a UUID")

    @staticmethod
    def _aware(name: str, value: datetime) -> None:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise InvalidAccountAccessTokenRequest(
                f"{name} must be timezone-aware"
            )
