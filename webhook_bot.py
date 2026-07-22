"""
Telegram bot with webhook mode using FastAPI.

This module sets up and runs a Telegram bot using aiogram with webhook
instead of polling. FastAPI handles incoming webhook requests.

Usage:
    python webhook_bot.py
    
Environment variables:
    WEBHOOK_URL - Base URL for webhook (e.g., https://yourdomain.com)
    WEBHOOK_PATH - Path for webhook endpoint (default: /webhook)
    WEBHOOK_SECRET - Secret token for webhook verification
"""

from contextlib import asynccontextmanager
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums.parse_mode import ParseMode
from aiogram.filters import ExceptionTypeFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import (
    DefaultKeyBuilder,
    RedisStorage,
)
from aiogram.types import Update
from aiogram_dialog import setup_dialogs
from aiogram_dialog.api.exceptions import (
    UnknownIntent,
    UnknownState,
    UnregisteredWindowError,
)

from app.internal import Container
from app.settings import config
from app.tgbot.dialogs import all_dialogs
from app.tgbot.handlers import routers_list
from app.tgbot.media_storage import RedisMediaIdStorage
from aiogram.exceptions import TelegramNetworkError
from app.tgbot.handlers.start import (
    on_network_error,
    on_unknown_intent,
    on_unknown_state,
    on_unregistered_window,
)
from app.tgbot.middlewares.config import ConfigMiddleware, StorageMiddleware
from app.tgbot.services import broadcaster


# Global instances
bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
container: Optional[Container] = None


async def on_startup(bot: Bot, admin_ids: List[int]):
    """Broadcast a startup message to the admin users."""
    await broadcaster.broadcast(bot, admin_ids, "Бот был запущен (webhook mode)")


def register_global_middlewares(dp: Dispatcher, config, storage):
    """Register global middlewares for the dispatcher."""
    middleware_types = [
        ConfigMiddleware(config),
        StorageMiddleware(storage),
    ]

    for middleware_type in middleware_types:
        dp.message.outer_middleware(middleware_type)
        dp.callback_query.outer_middleware(middleware_type)
        dp.chat_member.outer_middleware(middleware_type)
        dp.my_chat_member.outer_middleware(middleware_type)


def setup_logging():
    """Set up logging configuration using loguru."""
    import sys
    import logging
    
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    logger.info("Starting bot (webhook mode)")


def get_storage(config):
    """Return storage based on configuration."""
    if config.TGBOT_USE_REDIS:
        return RedisStorage.from_url(
            config.REDIS_DSN,
            key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
        )
    else:
        return MemoryStorage()


def setup_bot_and_dispatcher():
    """Initialize bot, dispatcher and container."""
    global bot, dp, container
    
    setup_logging()
    
    # Initialize container
    container = Container()
    container.wire(
        modules=[
            "app.tgbot.handlers.start",
            "app.tgbot.handlers",
            "app.tgbot.dialogs.organization.handlers",
            "app.tgbot.dialogs.organization.getters",
            "app.tgbot.dialogs.employee.handlers",
            "app.tgbot.dialogs.employee.getters",
            "app.tgbot.dialogs.criterion.handlers",
            "app.tgbot.dialogs.criterion.getters",
            "app.tgbot.dialogs.criterion_set.handlers",
            "app.tgbot.dialogs.criterion_set.getters",
            "app.tgbot.dialogs.evaluation.handlers",
            "app.tgbot.dialogs.evaluation.getters",
            "app.tgbot.dialogs.export.handlers",
            "app.tgbot.dialogs.analytics.handlers",
            "app.tgbot.dialogs.analytics.getters",
            "app.tgbot.dialogs.analytics.getters_objects",
            "app.tgbot.dialogs.common.organization",
            "app.tgbot.dialogs.common.evaluation_type",
            "app.tgbot.dialogs.common.criterion_set",
            "app.internal.services.pdf_report_service",
            "app.tgbot.dialogs.greeting.handlers",
            "app.tgbot.dialogs.greeting.getters",
            "app.tgbot.dialogs.greeting.windows",
            "app.tgbot.dialogs.help.handlers",
            "app.tgbot.dialogs.help.getters",
            "app.tgbot.filters.administrator",
            # API modules - only webapp (other routers not needed for bot)
            "app.api.deps",
            "app.api.routers.webapp",
        ]
    )
    
    storage = get_storage(config)
    
    bot = Bot(
        token=config.TGBOT_TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )
    
    dp = Dispatcher(storage=storage)
    
    media_storage = RedisMediaIdStorage(config.REDIS_DSN)
    setup_dialogs(dp, media_id_storage=media_storage)
    dp.include_routers(*routers_list, *all_dialogs())
    
    register_global_middlewares(dp, config, storage)
    dp.errors.register(on_unknown_intent, ExceptionTypeFilter(UnknownIntent))
    dp.errors.register(on_unknown_state, ExceptionTypeFilter(UnknownState))
    dp.errors.register(on_unregistered_window, ExceptionTypeFilter(UnregisteredWindowError))
    dp.errors.register(on_network_error, ExceptionTypeFilter(TelegramNetworkError))
    
    return bot, dp, container


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application."""
    global bot, dp, container
    
    # Setup bot and dispatcher
    bot, dp, container = setup_bot_and_dispatcher()
    
    # Set shared instances for API
    from app.api.main import set_shared_container, set_shared_bot
    set_shared_container(container)
    set_shared_bot(bot)
    
    # Setup webhook
    webhook_url = config.WEBHOOK_URL
    webhook_path = getattr(config, 'WEBHOOK_PATH', '/webhook')
    webhook_secret = getattr(config, 'WEBHOOK_SECRET', None)
    
    full_webhook_url = f"{webhook_url}{webhook_path}"
    
    logger.info(f"Setting webhook to: {full_webhook_url}")
    
    await bot.set_webhook(
        url=full_webhook_url,
        secret_token=webhook_secret,
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
    )
    
    await on_startup(bot, config.TGBOT_ADMIN_IDS)
    
    yield
    
    # Cleanup
    logger.info("Shutting down webhook bot...")
    
    # Cancel AI tasks
    from app.tgbot.dialogs.analytics.handlers import cancel_all_ai_tasks
    await cancel_all_ai_tasks()
    
    # Delete webhook
    await bot.delete_webhook()
    
    # Close bot session
    await bot.session.close()
    
    # Shutdown container
    container.shutdown_resources()
    container.unwire()
    
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure FastAPI application with webhook support."""
    from app.api.routers import webapp
    from app.settings import config as app_config
    
    app = FastAPI(
        title="Restos API + Webhook",
        description="API for Employee Evaluation System with Telegram Webhook (Web Forms Only)",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config.CORS_ORIGINS,
        allow_credentials=app_config.CORS_ALLOW_CREDENTIALS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Telegram-Id", "X-Telegram-Chat-Id", "X-Organization-Id"],
    )
    
    # Webhook endpoint
    @app.post("/webhook")
    async def webhook_handler(request: Request) -> Response:
        """Handle incoming Telegram webhook updates."""
        global bot, dp
        
        # Verify secret token if configured
        webhook_secret = getattr(config, 'WEBHOOK_SECRET', None)
        if webhook_secret:
            token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if token != webhook_secret:
                logger.warning("Invalid webhook secret token")
                return Response(status_code=403)
        
        # Parse update
        update_data = await request.json()
        update = Update.model_validate(update_data, context={"bot": bot})
        
        # Process update
        await dp.feed_update(bot=bot, update=update)
        
        return Response(status_code=200)
    
    # Include ONLY webapp router (web forms)
    # Other API endpoints are not needed when running with bot
    app.include_router(webapp.router, prefix="/api")  # /api/webapp/...
    
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "healthy", "mode": "webhook"}
    
    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": "Restos API + Webhook",
            "version": "1.0.0",
            "docs": "/docs",
            "redoc": "/redoc",
        }
    
    return app


# Create application instance
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "webhook_bot:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
