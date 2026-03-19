"""Global point to cached settings."""

import os
from pathlib import Path
from typing import List
from environs import Env


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
        self.DATABASE_URL = self.env.str("DATABASE_URL", default="postgresql+asyncpg://postgres:password@localhost:5432/yarbot")
        self.DATABASE_POOL_SIZE = self.env.int("DATABASE_POOL_SIZE", default=10)
        self.DATABASE_MAX_OVERFLOW = self.env.int("DATABASE_MAX_OVERFLOW", default=20)
        self.DATABASE_POOL_RECYCLE = self.env.int("DATABASE_POOL_RECYCLE", default=3600)
        
        # Web App settings
        # Frontend URL (Dioxus form)
        self.WEBAPP_BASE_URL = self.env.str("WEBAPP_BASE_URL", default="http://localhost:8080")
        # API URL (FastAPI) - if different from frontend (e.g., two tunnels)
        self.WEBAPP_API_URL = self.env.str("WEBAPP_API_URL", default="")
        # 32-byte key for ChaCha20Poly1305 (generate with: secrets.token_hex(32))
        self.WEBAPP_SECRET_KEY = self.env.str("WEBAPP_SECRET_KEY", default="0" * 64)  # Must be 64 hex chars
        # Token expiration in seconds (default 1 hour)
        self.WEBAPP_TOKEN_EXPIRY = self.env.int("WEBAPP_TOKEN_EXPIRY", default=3600)
        
        # JWT settings for web auth
        self.JWT_SECRET_KEY = self.env.str("JWT_SECRET_KEY", default="change-me-in-production-" + "0" * 32)
        self.JWT_ALGORITHM = "HS256"
        self.JWT_EXPIRE_DAYS = self.env.int("JWT_EXPIRE_DAYS", default=30)

        # Default admin user (created on first startup if not exists)
        self.DEFAULT_ADMIN_LOGIN = self.env.str("DEFAULT_ADMIN_LOGIN", default="admin")
        self.DEFAULT_ADMIN_PASSWORD = self.env.str("DEFAULT_ADMIN_PASSWORD", default="admin123")
        self.DEFAULT_ADMIN_NAME = self.env.str("DEFAULT_ADMIN_NAME", default="Главный администратор")
        self.DEFAULT_ORG_NAME = self.env.str("DEFAULT_ORG_NAME", default="Моя организация")
        self.DEFAULT_ORG_CODE = self.env.str("DEFAULT_ORG_CODE", default="main")

        # CORS settings for API
        # In production, set to specific origins (e.g., "https://yourdomain.com,https://webapp.yourdomain.com")
        self.CORS_ORIGINS = self.env.list("CORS_ORIGINS", default=["*"])
        self.CORS_ALLOW_CREDENTIALS = self.env.bool("CORS_ALLOW_CREDENTIALS", default=True)
        
        # Webhook settings (for webhook_bot.py)
        self.WEBHOOK_URL = self.env.str("WEBHOOK_URL", default="")  # e.g., https://yourdomain.com
        self.WEBHOOK_PATH = self.env.str("WEBHOOK_PATH", default="/webhook")
        self.WEBHOOK_SECRET = self.env.str("WEBHOOK_SECRET", default="")  # Secret token for verification


def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.env').exists():
            return current
        current = current.parent
    return Path(os.getcwd())


config = Config()
