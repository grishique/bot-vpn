"""Middleware for user registration and access control."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import channel_subscription_keyboard
from app.config.settings import get_settings
from app.services.user_service import user_service

SUBSCRIPTION_REQUIRED_TEXT = (
    "👋 <b>Добро пожаловать</b>\n"
    "Для работы с ботом вступите в канал VPN'а\n\n"
    "После того, как подпишитесь, пропишите /start"
)

ALLOWED_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


class AccessMiddleware(BaseMiddleware):
    """Attach current user data, stop banned users and require channel subscription."""

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession = data["session"]
        tg_user = data.get("event_from_user")

        if tg_user is None:
            return await handler(event, data)

        current_user = await user_service.get_or_create(session, tg_user)
        data["current_user"] = current_user

        if current_user.is_banned:
            if isinstance(event, Message):
                await event.answer("Ваш аккаунт заблокирован. Обратитесь в поддержку.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Ваш аккаунт заблокирован.", show_alert=True)
            elif isinstance(event, PreCheckoutQuery):
                await event.answer(ok=False, error_message="Оплата недоступна для этого аккаунта.")
            return None

        if current_user.telegram_id in get_settings().admin_ids:
            return await handler(event, data)

        is_subscribed = await self._is_subscribed(data, current_user.telegram_id)
        if is_subscribed:
            return await handler(event, data)

        await self._handle_unsubscribed(event)
        return None

    async def _is_subscribed(self, data: dict[str, Any], telegram_id: int) -> bool:
        """Check whether the user is subscribed to the required channel."""
        settings = get_settings()
        channel_username = settings.telegram_required_channel_username.strip().lstrip("@")
        if not channel_username:
            return True

        bot: Bot | None = data.get("bot")
        if bot is None:
            return False

        try:
            member = await bot.get_chat_member(chat_id=f"@{channel_username}", user_id=telegram_id)
        except (TelegramBadRequest, TelegramForbiddenError):
            return False

        return member.status in ALLOWED_MEMBER_STATUSES

    async def _handle_unsubscribed(self, event: Any) -> None:
        """Send or show the subscription requirement prompt."""
        settings = get_settings()
        keyboard = channel_subscription_keyboard(settings.telegram_required_channel_url)

        if isinstance(event, Message):
            await event.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=keyboard)
            return

        if isinstance(event, CallbackQuery):
            await event.answer("Сначала подпишитесь на канал и отправьте /start.", show_alert=True)
            if event.message is not None:
                await event.message.answer(SUBSCRIPTION_REQUIRED_TEXT, reply_markup=keyboard)
            return

        if isinstance(event, PreCheckoutQuery):
            await event.answer(
                ok=False,
                error_message="Сначала подпишитесь на канал VPN и отправьте /start.",
            )
