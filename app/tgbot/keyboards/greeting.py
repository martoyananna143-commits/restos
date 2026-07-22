"""Greeting keyboard."""

from aiogram.utils.keyboard import InlineKeyboardBuilder


def greeting_keyboard():
    """Create greeting keyboard.

    Returns:
        InlineKeyboardMarkup: The greeting keyboard.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Начать работу 🚀", callback_data="start_work")
    kb.button(text="Помощь ❓", callback_data="help")
    kb.adjust(1)
    return kb.as_markup()

