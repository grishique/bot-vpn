"""FastAPI entrypoint for the VPN SaaS bot."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import FastAPI

from app.api.routers.health import router as health_router
from app.api.routers.payments import router as payments_router
from app.api.routers.subscriptions import router as subscriptions_router
from app.api.routers.webhook import router as webhook_router
from app.bot.dispatcher import configure_bot, create_bot, create_dispatcher
from app.config.logging import setup_logging
from app.config.settings import get_settings
from app.database.session import AsyncSessionFactory
from app.services.bootstrap_service import bootstrap_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the bot, dispatcher and webhook lifecycle."""
    settings = get_settings()
    setup_logging(settings.log_level)

    bot = create_bot()
    dispatcher = create_dispatcher()
    app.state.bot = bot
    app.state.dispatcher = dispatcher
    app.state.session_factory = AsyncSessionFactory
    webhook_registered = False

    try:
        async with AsyncSessionFactory() as session:
            await bootstrap_service.ensure_seed_data(session)
            await bootstrap_service.sync_admin_roles(session)
            await session.commit()

        await configure_bot(
            bot,
            configure_commands=(
                settings.telegram_set_commands_on_startup and not settings.telegram_use_polling
            ),
        )
        if settings.telegram_use_polling:
            logger.info("Application started in polling mode. Webhook registration skipped.")
        elif settings.telegram_set_webhook_on_startup:
            await bot.set_webhook(
                url=settings.telegram_webhook_url,
                secret_token=settings.telegram_webhook_secret,
                allowed_updates=dispatcher.resolve_used_update_types(),
            )
            webhook_registered = True
            logger.info("Webhook configured at %s", settings.telegram_webhook_url)
        else:
            logger.info("Webhook registration skipped by configuration.")

        yield
    finally:
        if webhook_registered:
            with suppress(Exception):
                await bot.delete_webhook(drop_pending_updates=False)
        await bot.session.close()
        await dispatcher.storage.close()


def create_application() -> FastAPI:
    """Build the FastAPI application instance."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(health_router, prefix=settings.api_prefix)
    app.include_router(payments_router, prefix=settings.api_prefix)
    app.include_router(subscriptions_router, prefix=settings.api_prefix)
    app.include_router(webhook_router, prefix=settings.telegram_webhook_path)
    return app


app = create_application()
