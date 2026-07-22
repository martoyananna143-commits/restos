from aiogram.filters import BaseFilter
from aiogram.types import Message

from app.settings import Config


class AdminFilter(BaseFilter):
    is_admin: bool = True

    async def __call__(self, obj: Message, config: Config) -> bool:
        if (obj.from_user.id in config.TGBOT_ADMIN_IDS) == self.is_admin:
            return True
        return False
