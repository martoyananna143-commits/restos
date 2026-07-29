"""Global point to cached settings."""

import logging
import os
from pathlib import Path
from urllib.parse import urlsplit
from environs import Env

_log = logging.getLogger(__name__)

_INSECURE_JWT_KEYS = {"change-me-in-production-" + "0" * 32}
_INSECURE_WEBAPP_KEYS = {"0" * 64}
_INSECURE_ADMIN_PASSWORDS = {"admin123", "admin", "password", "12345678"}


class Config:
    """Configuration class for the bot."""

    def __init__(self):
        self.env = Env()
        self.env.read_env()

        # Bot settings
        self.TGBOT_TOKEN = self.env.str("TGBOT_TOKEN")
        self.TGBOT_ADMIN_IDS = self.env.list("TGBOT_ADMIN_IDS", subcast=int)
        self.TGBOT_USE_REDIS = self.env.bool("TGBOT_USE_REDIS", default=True)
        self.TGBOT_TRIGGER_MESSAGE_BUSINESS_CHAT = self.env.str("TGBOT_TRIGGER_MESSAGE_BUSINESS_CHAT", default="start")
        self.TGBOT_TRIGGER_AUTO_MESSAGE_BUSINESS_CHAT = self.env.str("TGBOT_TRIGGER_AUTO_MESSAGE_BUSINESS_CHAT", default="help")

        # Redis settings
        self.REDIS_DSN = self.env.str("REDIS_DSN", default="redis://localhost:6379/0")

        # Database settings
        self.DATABASE_URL = self.env.str("DATABASE_URL", default="postgresql+asyncpg://postgres:password@localhost:5432/restos")
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
        self.SMS_PROVIDER = self.env.str("SMS_PROVIDER", default="disabled")
        self.SMS_AERO_EMAIL = self.env.str("SMS_AERO_EMAIL", default="")
        self.SMS_AERO_API_KEY = self.env.str("SMS_AERO_API_KEY", default="")
        self.SMS_AERO_SIGN = self.env.str("SMS_AERO_SIGN", default="")
        self.SMS_AERO_BASE_URL = self.env.str("SMS_AERO_BASE_URL", default="")
        self.SMS_HTTP_TIMEOUT_SECONDS = self.env.float(
            "SMS_HTTP_TIMEOUT_SECONDS", default=10.0
        )

        # Web App settings
        self.WEBAPP_BASE_URL = self.env.str("WEBAPP_BASE_URL", default="http://localhost:8080")
        self.WEBAPP_API_URL = self.env.str("WEBAPP_API_URL", default="")
        # 32-byte key for ChaCha20Poly1305 (generate with: python -c "import secrets; print(secrets.token_hex(32))")
        self.WEBAPP_SECRET_KEY = self.env.str("WEBAPP_SECRET_KEY", default="0" * 64)
        self.WEBAPP_TOKEN_EXPIRY = self.env.int("WEBAPP_TOKEN_EXPIRY", default=3600)

        # Internal API key — required for bot→API token-mint endpoints (/webapp/token, /webapp/page-token).
        # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
        # When empty the endpoints are open (acceptable for local dev only).
        self.INTERNAL_API_KEY = self.env.str("INTERNAL_API_KEY", default="")

        # JWT settings for web auth
        self.JWT_SECRET_KEY = self.env.str("JWT_SECRET_KEY", default="change-me-in-production-" + "0" * 32)
        self.JWT_ALGORITHM = "HS256"
        self.JWT_EXPIRE_DAYS = self.env.int("JWT_EXPIRE_DAYS", default=30)
        # Web app: second-factor PIN must be re-entered if JWT claim ``pva`` is older than this (seconds).
        self.WEB_PIN_MAX_AGE_SECONDS = self.env.int("WEB_PIN_MAX_AGE_SECONDS", default=86400)

        # Default admin user (created on first startup if not exists)
        self.DEFAULT_ADMIN_LOGIN = self.env.str("DEFAULT_ADMIN_LOGIN", default="admin")
        self.DEFAULT_ADMIN_PASSWORD = self.env.str("DEFAULT_ADMIN_PASSWORD", default="admin123")
        self.DEFAULT_ADMIN_NAME = self.env.str("DEFAULT_ADMIN_NAME", default="Главный администратор")
        self.DEFAULT_ORG_NAME = self.env.str("DEFAULT_ORG_NAME", default="Моя организация")
        self.DEFAULT_ORG_CODE = self.env.str("DEFAULT_ORG_CODE", default="main")

        # Superuser login — this account has cross-org access without needing
        # an employee record in each org. Defaults to the default admin login.
        self.SUPERUSER_LOGIN = self.env.str("SUPERUSER_LOGIN", default=self.DEFAULT_ADMIN_LOGIN)

        # CORS settings for API
        self.CORS_ORIGINS = self.env.list("CORS_ORIGINS", default=["*"])
        self.CORS_ALLOW_CREDENTIALS = self.env.bool("CORS_ALLOW_CREDENTIALS", default=True)

        # Google Sheets / Drive (live criterion templates)
        self.GOOGLE_SHEETS_FETCH_TIMEOUT = self.env.float("GOOGLE_SHEETS_FETCH_TIMEOUT", default=15.0)
        self.GOOGLE_SHEETS_MAX_ROWS = self.env.int("GOOGLE_SHEETS_MAX_ROWS", default=500)
        # Path to service account JSON file OR leave empty and use GOOGLE_SERVICE_ACCOUNT_JSON_DATA
        self.GOOGLE_SERVICE_ACCOUNT_JSON = self.env.str("GOOGLE_SERVICE_ACCOUNT_JSON", default="")
        self.GOOGLE_SERVICE_ACCOUNT_JSON_DATA = self.env.str("GOOGLE_SERVICE_ACCOUNT_JSON_DATA", default="")

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
        if self.JWT_SECRET_KEY in _INSECURE_JWT_KEYS:
            errors.append("JWT_SECRET_KEY is using an insecure default — set a strong random value")
        if self.WEBAPP_SECRET_KEY in _INSECURE_WEBAPP_KEYS:
            errors.append("WEBAPP_SECRET_KEY is using an insecure default (64 zeros) — generate a real key")
        if self.DEFAULT_ADMIN_PASSWORD in _INSECURE_ADMIN_PASSWORDS:
            errors.append(f"DEFAULT_ADMIN_PASSWORD is '{self.DEFAULT_ADMIN_PASSWORD}' — change it before deploying")
        if not self.INTERNAL_API_KEY:
            errors.append("INTERNAL_API_KEY is not set — bot token-mint endpoints are unprotected")
        if self.CORS_ORIGINS == ["*"] and self.CORS_ALLOW_CREDENTIALS:
            errors.append("CORS_ORIGINS='*' with CORS_ALLOW_CREDENTIALS=True is rejected by browsers and insecure")
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
        if errors:
            raise RuntimeError(
                "Production security checks failed — fix the following before starting:\n"
                + "\n".join(f"  • {e}" for e in errors)
            )
        if self.CORS_ORIGINS == ["*"]:
            _log.warning("CORS_ORIGINS is '*' — restrict to specific origins in production")


def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.env').exists():
            return current
        current = current.parent
    return Path(os.getcwd())


config = Config()
