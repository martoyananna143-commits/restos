"""Helper for generating Telegram Mini Web App URLs from bot handlers.

Reuses the ChaCha20 token generation from the API webapp router directly,
avoiding an HTTP round-trip for token creation.
"""

from typing import Optional

from aiogram.types import Message

from app.api.routers.webapp import create_page_token
from app.settings import config

PAGE_QUERY_NAMES = {
    "employees": "employees",
    "evaluations": "evaluations",
    "analytics": "analytics",
    "criteria_select": "criteria-select",
}


def generate_page_url(
    page: str,
    org_id: int,
    user_telegram_id: int,
    extra: Optional[dict] = None,
) -> str:
    """Generate a full Mini Web App URL for the given page type.

    Dioxus frontend dispatches by ?page= query param on root /, NOT by path.
    """
    token = create_page_token(
        page=page,
        org_id=org_id,
        user_telegram_id=user_telegram_id,
        extra=extra,
    )
    query_page = PAGE_QUERY_NAMES.get(page, page)
    return f"{config.WEBAPP_BASE_URL}/?page={query_page}&token={token}"


def _is_localhost_url(url: str) -> bool:
    """Return True when URL cannot be used as a Telegram WebApp (non-HTTPS)."""
    return url.startswith("http://") or "localhost" in url or "127.0.0.1" in url


async def send_webapp_or_link(
    message: Optional[Message],
    url: str,
    text: str,
    button_text: str,
) -> None:
    """Send a WebApp inline button, or a plain-text link on localhost/HTTP.

    Telegram rejects non-HTTPS WebApp URLs in development, so we fall back
    to the same plain-message pattern used for evaluation form tokens.
    """
    if message is None:
        return

    if _is_localhost_url(url):
        await message.answer(
            f"{text}\n\n🔗 <code>{url}</code>",
            parse_mode="HTML",
        )
        return

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=button_text, web_app=WebAppInfo(url=url))],
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
