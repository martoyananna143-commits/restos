from aiogram.types import WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.settings import config


def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(
        text="Start MiniApp🚀",
        web_app=WebAppInfo(url=str(config.API.FRONTEND_URL)),
    )
    kb.button(
        text="Start WebApp😸",
        url=str(config.API.SITE_URL),
    )
    kb.adjust(1)
    return kb.as_markup()
