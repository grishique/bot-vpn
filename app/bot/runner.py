"""Standalone Telegram bot runner for long polling mode."""

from __future__ import annotations

import asyncio
import logging

from app.bot.dispatcher import configure_bot, create_bot, create_dispatcher
from app.config.logging import setup_logging
from app.config.settings import get_settings
from app.database.session import AsyncSessionFactory
from app.services.bootstrap_service import bootstrap_service

logger = logging.getLogger(__name__)


async def run_polling() -> None:
    """Start the Telegram bot in long polling mode."""
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.telegram_use_polling:
        logger.warning("Polling runner started while TELEGRAM_USE_POLLING is disabled.")
        return

    bot = create_bot()
    dispatcher = create_dispatcher()

    try:
        async with AsyncSessionFactory() as session:
            await bootstrap_service.ensure_seed_data(session)
            await bootstrap_service.sync_admin_roles(session)
            await session.commit()

        await bot.delete_webhook(drop_pending_updates=False)
        await configure_bot(bot, configure_commands=settings.telegram_set_commands_on_startup)
        logger.info("Starting Telegram bot in polling mode.")
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()
        await dispatcher.storage.close()


def main() -> None:
    """Run the polling worker entrypoint."""
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
