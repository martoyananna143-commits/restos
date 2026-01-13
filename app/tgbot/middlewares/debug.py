"""Debug middleware for logging all updates."""

import logging
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Update

logger = logging.getLogger(__name__)


class DebugMiddleware(BaseMiddleware):
    """Middleware for debugging updates."""

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        """Log all updates."""
        logger.info(f"Processing update: {event.model_dump()}")
        return await handler(event, data)
