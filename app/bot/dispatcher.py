"""Factory functions for bot and dispatcher instances."""

from __future__ import annotations

import logging

from aiogram import Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage

from app.bot.branded_bot import BrandedBot
from app.bot.commands import setup_commands
from app.bot.handlers.admin import router as admin_router
from app.bot.handlers.common import router as common_router
from app.bot.handlers.payments import router as payments_router
from app.bot.handlers.promo import router as promo_router
from app.bot.handlers.purchase import router as purchase_router
from app.bot.handlers.subscription import router as subscription_router
from app.bot.middlewares.access import AccessMiddleware
from app.bot.middlewares.db import DatabaseSessionMiddleware
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


def create_bot() -> BrandedBot:
    """Build the aiogram Bot object."""
    settings = get_settings()
    return BrandedBot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=settings.telegram_parse_mode),
    )


def create_dispatcher() -> Dispatcher:
    """Build the aiogram Dispatcher object."""
    settings = get_settings()
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    root_router = Router()
    root_router.message.outer_middleware(DatabaseSessionMiddleware())
    root_router.callback_query.outer_middleware(DatabaseSessionMiddleware())
    root_router.pre_checkout_query.outer_middleware(DatabaseSessionMiddleware())

    root_router.message.middleware(AccessMiddleware())
    root_router.callback_query.middleware(AccessMiddleware())
    root_router.pre_checkout_query.middleware(AccessMiddleware())

    root_router.include_router(common_router)
    root_router.include_router(purchase_router)
    root_router.include_router(subscription_router)
    root_router.include_router(promo_router)
    root_router.include_router(payments_router)
    root_router.include_router(admin_router)

    dp.include_router(root_router)
    return dp


async def configure_bot(bot: Bot, configure_commands: bool = True) -> None:
    """Apply runtime bot settings such as commands."""
    if not configure_commands:
        logger.info("Telegram command registration skipped by configuration.")
        return

    await setup_commands(bot)
    logger.info("Telegram commands configured.")
