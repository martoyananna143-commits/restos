"""Global point to cached settings."""

import logging
import os
import ipaddress
from pathlib import Path
import re
from urllib.parse import urlsplit
from environs import Env

_log = logging.getLogger(__name__)

_INSECURE_JWT_KEYS = {"change-me-in-production-" + "0" * 32}
_INSECURE_WEBAPP_KEYS = {"0" * 64}
_INSECURE_ADMIN_PASSWORDS = {"admin123", "admin", "password", "12345678"}
_WEBAUTHN_RP_ID = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_WEBAUTHN_MAX_CHALLENGE_TTL_SECONDS = 600
_WEBAUTHN_MAX_VERIFY_ATTEMPTS = 10


class Config:
    """Configuration class for the bot."""

    def __init__(self):
        self.env = Env()
        self.env.read_env()

        # Bot settings
        self.TGBOT_TOKEN = self.env.str("TGBOT_TOKEN")
        self.TGBOT_ADMIN_IDS = self.env.list("TGBOT_ADMIN_IDS", subcast=int)
        self.TGBOT_USE_REDIS = self.env.bool("TGBOT_USE_REDIS", default=True)
        self.TGBOT_TRIGGER_MESSAGE_BUSINESS_CHAT = self.env.str(
            "TGBOT_TRIGGER_MESSAGE_BUSINESS_CHAT", default="start"
        )
        self.TGBOT_TRIGGER_AUTO_MESSAGE_BUSINESS_CHAT = self.env.str(
            "TGBOT_TRIGGER_AUTO_MESSAGE_BUSINESS_CHAT", default="help"
        )

        # Redis settings
        self.REDIS_DSN = self.env.str("REDIS_DSN", default="redis://localhost:6379/0")

        # Database settings
        self.DATABASE_URL = self.env.str(
            "DATABASE_URL",
            default="postgresql+asyncpg://postgres:password@localhost:5432/restos",
        )
        self.DATABASE_POOL_SIZE = self.env.int("DATABASE_POOL_SIZE", default=10)
        self.DATABASE_MAX_OVERFLOW = self.env.int("DATABASE_MAX_OVERFLOW", default=20)
        self.DATABASE_POOL_RECYCLE = self.env.int("DATABASE_POOL_RECYCLE", default=3600)

        # Additive Account-auth settings. Secret values have no production
        # fallback and are only consumed by the new invitation auth router.
        self.ACCOUNT_AUTH_INVITATION_PEPPER = self.env.str(
            "ACCOUNT_AUTH_INVITATION_PEPPER", default=""
        )
        self.ACCOUNT_AUTH_PHONE_PEPPER = self.env.str(
            "ACCOUNT_AUTH_PHONE_PEPPER", default=""
        )
        self.ACCOUNT_AUTH_CODE_PEPPER = self.env.str(
            "ACCOUNT_AUTH_CODE_PEPPER", default=""
        )
        self.ACCOUNT_AUTH_SESSION_PEPPER = self.env.str(
            "ACCOUNT_AUTH_SESSION_PEPPER", default=""
        )
        self.ACCOUNT_GROUP_INVITATION_PEPPER = self.env.str(
            "ACCOUNT_GROUP_INVITATION_PEPPER", default=""
        )
        self.ACCOUNT_GROUP_ONBOARDING_DOB_LEGAL_PUBLISHED = self.env.bool(
            "ACCOUNT_GROUP_ONBOARDING_DOB_LEGAL_PUBLISHED", default=False
        )
        self.ACCOUNT_AUTH_ACCESS_TOKEN_KEY = self.env.str(
            "ACCOUNT_AUTH_ACCESS_TOKEN_KEY", default=""
        )
        self.ACCOUNT_AUTH_ACCESS_TOKEN_TTL_SECONDS = self.env.int(
            "ACCOUNT_AUTH_ACCESS_TOKEN_TTL_SECONDS", default=600
        )
        self.ACCOUNT_WEB_REFRESH_COOKIE_NAME = self.env.str(
            "ACCOUNT_WEB_REFRESH_COOKIE_NAME", default="restos_refresh"
        )
        self.ACCOUNT_WEB_REFRESH_COOKIE_SECURE = self.env.bool(
            "ACCOUNT_WEB_REFRESH_COOKIE_SECURE",
            default=self.env.str("APP_ENV", default="development") == "production",
        )
        self.ACCOUNT_WEB_REFRESH_COOKIE_SAMESITE = self.env.str(
            "ACCOUNT_WEB_REFRESH_COOKIE_SAMESITE", default="lax"
        )
        self.ACCOUNT_WEB_ALLOWED_ORIGINS = self.env.list(
            "ACCOUNT_WEB_ALLOWED_ORIGINS", default=[]
        )
        self.ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN = self.env.str(
            "ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN", default=""
        )
        self.WEBAUTHN_RP_ID = self.env.str("WEBAUTHN_RP_ID", default="")
        self.WEBAUTHN_RP_NAME = self.env.str("WEBAUTHN_RP_NAME", default="")
        self.WEBAUTHN_ALLOWED_ORIGINS = self.env.list(
            "WEBAUTHN_ALLOWED_ORIGINS", default=[]
        )
        self.WEBAUTHN_CHALLENGE_TTL_SECONDS = self.env.int(
            "WEBAUTHN_CHALLENGE_TTL_SECONDS", default=300
        )
        self.WEBAUTHN_MAX_VERIFY_ATTEMPTS = self.env.int(
            "WEBAUTHN_MAX_VERIFY_ATTEMPTS", default=3
        )
        self.SMS_PROVIDER = self.env.str("SMS_PROVIDER", default="disabled")
        self.SMS_AERO_EMAIL = self.env.str("SMS_AERO_EMAIL", default="")
        self.SMS_AERO_API_KEY = self.env.str("SMS_AERO_API_KEY", default="")
        self.SMS_AERO_SIGN = self.env.str("SMS_AERO_SIGN", default="")
        self.SMS_AERO_BASE_URL = self.env.str("SMS_AERO_BASE_URL", default="")
        self.SMS_HTTP_TIMEOUT_SECONDS = self.env.float(
            "SMS_HTTP_TIMEOUT_SECONDS", default=10.0
        )

        # Private application media.  Credentials intentionally have no
        # fallback and are consumed only by the backend S3 adapter.
        self.TASK_MEDIA_PROVIDER = self.env.str(
            "TASK_MEDIA_PROVIDER", default="disabled"
        )
        self.TASK_MEDIA_S3_ENDPOINT = self.env.str("TASK_MEDIA_S3_ENDPOINT", default="")
        self.TASK_MEDIA_S3_BUCKET = self.env.str("TASK_MEDIA_S3_BUCKET", default="")
        self.TASK_MEDIA_S3_REGION = self.env.str(
            "TASK_MEDIA_S3_REGION", default="us-east-1"
        )
        self.TASK_MEDIA_S3_ACCESS_KEY_ID = self.env.str(
            "TASK_MEDIA_S3_ACCESS_KEY_ID", default=""
        )
        self.TASK_MEDIA_S3_SECRET_ACCESS_KEY = self.env.str(
            "TASK_MEDIA_S3_SECRET_ACCESS_KEY", default=""
        )
        self.TASK_MEDIA_S3_CA_FILE = self.env.str("TASK_MEDIA_S3_CA_FILE", default="")
        self.TASK_MEDIA_S3_SSE = self.env.str("TASK_MEDIA_S3_SSE", default="AES256")
        self.TASK_MEDIA_TEMPORARY_TTL_HOURS = self.env.int(
            "TASK_MEDIA_TEMPORARY_TTL_HOURS", default=48
        )

        # Web App settings
        self.WEBAPP_BASE_URL = self.env.str(
            "WEBAPP_BASE_URL", default="http://localhost:8080"
        )
        self.WEBAPP_API_URL = self.env.str("WEBAPP_API_URL", default="")
        # 32-byte key for ChaCha20Poly1305 (generate with: python -c "import secrets; print(secrets.token_hex(32))")
        self.WEBAPP_SECRET_KEY = self.env.str("WEBAPP_SECRET_KEY", default="0" * 64)
        self.WEBAPP_TOKEN_EXPIRY = self.env.int("WEBAPP_TOKEN_EXPIRY", default=3600)

        # Internal API key — required for bot→API token-mint endpoints (/webapp/token, /webapp/page-token).
        # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
        # When empty the endpoints are open (acceptable for local dev only).
        self.INTERNAL_API_KEY = self.env.str("INTERNAL_API_KEY", default="")

        # JWT settings for web auth
        self.JWT_SECRET_KEY = self.env.str(
            "JWT_SECRET_KEY", default="change-me-in-production-" + "0" * 32
        )
        self.JWT_ALGORITHM = "HS256"
        self.JWT_EXPIRE_DAYS = self.env.int("JWT_EXPIRE_DAYS", default=30)
        # Web app: second-factor PIN must be re-entered if JWT claim ``pva`` is older than this (seconds).
        self.WEB_PIN_MAX_AGE_SECONDS = self.env.int(
            "WEB_PIN_MAX_AGE_SECONDS", default=86400
        )

        # Default admin user (created on first startup if not exists)
        self.DEFAULT_ADMIN_LOGIN = self.env.str("DEFAULT_ADMIN_LOGIN", default="admin")
        self.DEFAULT_ADMIN_PASSWORD = self.env.str(
            "DEFAULT_ADMIN_PASSWORD", default="admin123"
        )
        self.DEFAULT_ADMIN_NAME = self.env.str(
            "DEFAULT_ADMIN_NAME", default="Главный администратор"
        )
        self.DEFAULT_ORG_NAME = self.env.str(
            "DEFAULT_ORG_NAME", default="Моя организация"
        )
        self.DEFAULT_ORG_CODE = self.env.str("DEFAULT_ORG_CODE", default="main")
        self.LEGACY_DEFAULT_ADMIN_BOOTSTRAP_ENABLED = self.env.bool(
            "LEGACY_DEFAULT_ADMIN_BOOTSTRAP_ENABLED",
            default=self.env.str("APP_ENV", default="development") != "production",
        )

        # Superuser login — this account has cross-org access without needing
        # an employee record in each org. Defaults to the default admin login.
        self.SUPERUSER_LOGIN = self.env.str(
            "SUPERUSER_LOGIN", default=self.DEFAULT_ADMIN_LOGIN
        )

        # CORS settings for API
        self.CORS_ORIGINS = self.env.list("CORS_ORIGINS", default=["*"])
        self.CORS_ALLOW_CREDENTIALS = self.env.bool(
            "CORS_ALLOW_CREDENTIALS", default=True
        )

        # Google Sheets / Drive (live criterion templates)
        self.GOOGLE_SHEETS_FETCH_TIMEOUT = self.env.float(
            "GOOGLE_SHEETS_FETCH_TIMEOUT", default=15.0
        )
        self.GOOGLE_SHEETS_MAX_ROWS = self.env.int(
            "GOOGLE_SHEETS_MAX_ROWS", default=500
        )
        # Path to service account JSON file OR leave empty and use GOOGLE_SERVICE_ACCOUNT_JSON_DATA
        self.GOOGLE_SERVICE_ACCOUNT_JSON = self.env.str(
            "GOOGLE_SERVICE_ACCOUNT_JSON", default=""
        )
        self.GOOGLE_SERVICE_ACCOUNT_JSON_DATA = self.env.str(
            "GOOGLE_SERVICE_ACCOUNT_JSON_DATA", default=""
        )

        # Deployment environment: "development" or "production"
        self.APP_ENV = self.env.str("APP_ENV", default="development")

        # Webhook settings (for webhook_bot.py)
        self.WEBHOOK_URL = self.env.str("WEBHOOK_URL", default="")
        self.WEBHOOK_PATH = self.env.str("WEBHOOK_PATH", default="/webhook")
        self.WEBHOOK_SECRET = self.env.str("WEBHOOK_SECRET", default="")

    def validate_production_security(self) -> None:
        """Raise RuntimeError if any critical secret is using an insecure default in production."""
        if self.APP_ENV != "production":
            return
        errors: list[str] = []
        if len(self.ACCOUNT_GROUP_INVITATION_PEPPER.encode("utf-8")) < 32:
            errors.append(
                "ACCOUNT_GROUP_INVITATION_PEPPER must contain at least 32 bytes"
            )
        if self.JWT_SECRET_KEY in _INSECURE_JWT_KEYS:
            errors.append(
                "JWT_SECRET_KEY is using an insecure default — set a strong random value"
            )
        if self.WEBAPP_SECRET_KEY in _INSECURE_WEBAPP_KEYS:
            errors.append(
                "WEBAPP_SECRET_KEY is using an insecure default (64 zeros) — generate a real key"
            )
        if self.DEFAULT_ADMIN_PASSWORD in _INSECURE_ADMIN_PASSWORDS:
            errors.append(
                f"DEFAULT_ADMIN_PASSWORD is '{self.DEFAULT_ADMIN_PASSWORD}' — change it before deploying"
            )
        if not self.INTERNAL_API_KEY:
            errors.append(
                "INTERNAL_API_KEY is not set — bot token-mint endpoints are unprotected"
            )
        if self.CORS_ORIGINS == ["*"] and self.CORS_ALLOW_CREDENTIALS:
            errors.append(
                "CORS_ORIGINS='*' with CORS_ALLOW_CREDENTIALS=True is rejected by browsers and insecure"
            )
        rp_id = self.WEBAUTHN_RP_ID
        if (
            not isinstance(rp_id, str)
            or not rp_id
            or rp_id != rp_id.strip().lower()
            or not _WEBAUTHN_RP_ID.fullmatch(rp_id)
            or rp_id == "localhost"
        ):
            errors.append("WEBAUTHN_RP_ID must be a production hostname")
        else:
            try:
                ipaddress.ip_address(rp_id)
            except ValueError:
                pass
            else:
                errors.append("WEBAUTHN_RP_ID must not be an IP address")
        if (
            not isinstance(self.WEBAUTHN_RP_NAME, str)
            or not self.WEBAUTHN_RP_NAME.strip()
        ):
            errors.append("WEBAUTHN_RP_NAME must be non-empty")
        origins = self.WEBAUTHN_ALLOWED_ORIGINS
        if not isinstance(origins, list) or not origins:
            errors.append("WEBAUTHN_ALLOWED_ORIGINS must be non-empty")
        else:
            for origin in origins:
                parsed_origin = urlsplit(origin) if isinstance(origin, str) else None
                hostname = parsed_origin.hostname if parsed_origin else None
                try:
                    invalid_port = parsed_origin.port is not None and not (
                        1 <= parsed_origin.port <= 65535
                    )
                except ValueError:
                    invalid_port = True
                if (
                    not isinstance(origin, str)
                    or not origin
                    or origin != origin.strip()
                    or "*" in origin
                    or parsed_origin is None
                    or parsed_origin.scheme != "https"
                    or not hostname
                    or parsed_origin.username is not None
                    or parsed_origin.password is not None
                    or parsed_origin.path not in {"", "/"}
                    or parsed_origin.query
                    or parsed_origin.fragment
                    or invalid_port
                    or not rp_id
                    or not (hostname == rp_id or hostname.endswith("." + rp_id))
                ):
                    errors.append("WEBAUTHN_ALLOWED_ORIGINS contains an unsafe origin")
                    break
        if (
            isinstance(self.WEBAUTHN_CHALLENGE_TTL_SECONDS, bool)
            or not isinstance(self.WEBAUTHN_CHALLENGE_TTL_SECONDS, int)
            or not 1
            <= self.WEBAUTHN_CHALLENGE_TTL_SECONDS
            <= _WEBAUTHN_MAX_CHALLENGE_TTL_SECONDS
        ):
            errors.append("WEBAUTHN_CHALLENGE_TTL_SECONDS is invalid")
        if (
            isinstance(self.WEBAUTHN_MAX_VERIFY_ATTEMPTS, bool)
            or not isinstance(self.WEBAUTHN_MAX_VERIFY_ATTEMPTS, int)
            or not 1
            <= self.WEBAUTHN_MAX_VERIFY_ATTEMPTS
            <= _WEBAUTHN_MAX_VERIFY_ATTEMPTS
        ):
            errors.append("WEBAUTHN_MAX_VERIFY_ATTEMPTS is invalid")
        sms_provider = self.SMS_PROVIDER.strip().lower()
        if sms_provider not in {"", "disabled", "smsaero"}:
            errors.append("SMS_PROVIDER must be 'disabled' or 'smsaero'")
        elif sms_provider == "smsaero":
            required_sms_settings = {
                "SMS_AERO_EMAIL": self.SMS_AERO_EMAIL,
                "SMS_AERO_API_KEY": self.SMS_AERO_API_KEY,
                "SMS_AERO_SIGN": self.SMS_AERO_SIGN,
                "SMS_AERO_BASE_URL": self.SMS_AERO_BASE_URL,
                "ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN": self.ACCOUNT_AUTH_SMS_AUTOFILL_DOMAIN,
            }
            missing_sms_settings = [
                name
                for name, value in required_sms_settings.items()
                if not isinstance(value, str) or not value.strip()
            ]
            if missing_sms_settings:
                errors.append(
                    "SMS_PROVIDER='smsaero' requires: "
                    + ", ".join(missing_sms_settings)
                )
            if self.SMS_AERO_SIGN != "SMS Aero":
                errors.append("SMS_AERO_SIGN must be the approved sender 'SMS Aero'")
            parsed_sms_url = urlsplit(self.SMS_AERO_BASE_URL.strip())
            if (
                parsed_sms_url.scheme != "https"
                or not parsed_sms_url.hostname
                or parsed_sms_url.username is not None
                or parsed_sms_url.password is not None
                or parsed_sms_url.query
                or parsed_sms_url.fragment
            ):
                errors.append("SMS_AERO_BASE_URL must be a safe HTTPS URL")
            if self.SMS_HTTP_TIMEOUT_SECONDS <= 0:
                errors.append("SMS_HTTP_TIMEOUT_SECONDS must be positive")
        media_provider = self.TASK_MEDIA_PROVIDER.strip().lower()
        if media_provider not in {"disabled", "s3"}:
            errors.append("TASK_MEDIA_PROVIDER must be 'disabled' or 's3'")
        elif media_provider == "s3":
            required_media_settings = {
                "TASK_MEDIA_S3_ENDPOINT": self.TASK_MEDIA_S3_ENDPOINT,
                "TASK_MEDIA_S3_BUCKET": self.TASK_MEDIA_S3_BUCKET,
                "TASK_MEDIA_S3_ACCESS_KEY_ID": self.TASK_MEDIA_S3_ACCESS_KEY_ID,
                "TASK_MEDIA_S3_SECRET_ACCESS_KEY": self.TASK_MEDIA_S3_SECRET_ACCESS_KEY,
            }
            missing_media_settings = [
                name
                for name, value in required_media_settings.items()
                if not isinstance(value, str) or not value.strip()
            ]
            if missing_media_settings:
                errors.append(
                    "TASK_MEDIA_PROVIDER='s3' requires: "
                    + ", ".join(missing_media_settings)
                )
            endpoint = urlsplit(self.TASK_MEDIA_S3_ENDPOINT.strip())
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username is not None
                or endpoint.password is not None
                or endpoint.path not in {"", "/"}
                or endpoint.query
                or endpoint.fragment
            ):
                errors.append("TASK_MEDIA_S3_ENDPOINT must be a safe HTTPS origin")
            if self.TASK_MEDIA_S3_SSE != "AES256":
                errors.append("TASK_MEDIA_S3_SSE must be AES256")
            if not 1 <= self.TASK_MEDIA_TEMPORARY_TTL_HOURS <= 48:
                errors.append("TASK_MEDIA_TEMPORARY_TTL_HOURS must be between 1 and 48")
        if errors:
            raise RuntimeError(
                "Production security checks failed — fix the following before starting:\n"
                + "\n".join(f"  • {e}" for e in errors)
            )
        if self.CORS_ORIGINS == ["*"]:
            _log.warning(
                "CORS_ORIGINS is '*' — restrict to specific origins in production"
            )


def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".env").exists():
            return current
        current = current.parent
    return Path(os.getcwd())


config = Config()
