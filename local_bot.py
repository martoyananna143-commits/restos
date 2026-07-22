"""
This module sets up and runs a Telegram bot using the aiogram library.

It includes functions for setting up logging, registering global middlewares,
and handling bot startup. The main function initializes the bot and starts polling.

Modules:
    asyncio
    typing
    loguru
    aiogram
    aiogram.fsm.storage.memory
    aiogram.fsm.storage.redis
    aiogram.client.default
    aiogram.filters
    aiogram_dialog
    tgbot.handlers.start
    tgbot.handlers
    tgbot.middlewares.config
    tgbot.services.broadcaster
    configuration.settings

Functions:
    on_startup(bot, admin_ids)
    register_global_middlewares(dp, config)
    setup_logging()
    get_storage(config)
    main()
"""

import asyncio
from typing import List

import uvicorn
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


async def on_startup(bot: Bot, admin_ids: List[int]):
    """
    Broadcast a startup message to the admin users.

    Args:
        bot (Bot): The bot instance.
        admin_ids (List[int]): List of admin user IDs.

    Returns:
        None
    """

    await broadcaster.broadcast(bot, admin_ids, "Бот был запущен")


def register_global_middlewares(dp: Dispatcher, config, storage):
    """
    Register global middlewares for the given dispatcher.

    Global middlewares here are the ones that are applied to all the handlers.

    Args:
        dp (Dispatcher): The dispatcher instance.
        config (Config): The configuration object from the loaded configuration.
        storage: Storage instance.

    Returns:
        None
    """

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
    """
    Set up logging configuration for the application using loguru.

    This method initializes the logging configuration for the application.
    It configures loguru with colorized output, proper formatting, and INFO level.
    Also intercepts standard logging to route it through loguru.

    Returns:
        None

    Example usage:
        setup_logging()
    """
    import sys
    import logging
    
    # Remove default handler
    logger.remove()
    
    # Add custom handler with colorized output and detailed format
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    
    # Intercept standard logging to route through loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # Get corresponding Loguru level if it exists
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # Find caller from where the logged message originated
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    # Replace standard logging handlers with loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    logger.info("Starting bot")


def get_storage(config):
    """
    Return storage based on the provided configuration.

    Args:
        config (Config): The configuration object.

    Returns:
        Storage: The storage object based on the configuration.
    """

    if config.TGBOT_USE_REDIS:
        return RedisStorage.from_url(
            config.REDIS_DSN,
            key_builder=DefaultKeyBuilder(with_bot_id=True, with_destiny=True),
        )
    else:
        return MemoryStorage()


async def run_api_server(container: Container, bot: Bot):
    """Run FastAPI server with uvicorn, sharing container and bot with API."""
    from app.api.main import app as fastapi_app, set_shared_container, set_shared_bot
    
    # Share container and bot with API
    set_shared_container(container)
    set_shared_bot(bot)
    
    config_uvicorn = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config_uvicorn)
    logger.info("Starting FastAPI server on http://0.0.0.0:8000")
    await server.serve()


async def main():
    """
    Main entry point for the bot application.

    This function sets up logging, initializes the bot and dispatcher,
    registers global middlewares, and starts polling.
    Also runs FastAPI server concurrently.

    Returns:
        None
    """

    setup_logging()

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
    dp.errors.register(
        on_unknown_intent,
        ExceptionTypeFilter(UnknownIntent),
    )
    dp.errors.register(
        on_unknown_state,
        ExceptionTypeFilter(UnknownState),
    )
    dp.errors.register(
        on_unregistered_window,
        ExceptionTypeFilter(UnregisteredWindowError),
    )
    dp.errors.register(
        on_network_error,
        ExceptionTypeFilter(TelegramNetworkError),
    )

    await on_startup(bot, config.TGBOT_ADMIN_IDS)
    
    # Run bot and API server concurrently
    try:
        await asyncio.gather(
            dp.start_polling(bot),
            run_api_server(container, bot),
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Received shutdown signal, cancelling AI tasks...")
    finally:
        # Cancel all active AI background tasks before shutdown
        from app.tgbot.dialogs.analytics.handlers import cancel_all_ai_tasks
        logger.info("Shutting down gracefully...")
        await cancel_all_ai_tasks()
        
        container.shutdown_resources()
        container.unwire()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот был выключен!")
