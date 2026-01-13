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


def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / '.env').exists():
            return current
        current = current.parent
    return Path(os.getcwd())


config = Config()
