"""Bot message helpers for subscription notifications."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.bot.keyboards.inline import subscription_access_keyboard, subscription_created_keyboard
from app.models.subscription import Subscription
from app.services.referral_service import CodexPassReward
from app.services.subscription_service import subscription_service
from app.services.xui_service import xui_service
from app.utils.qr import build_qr_code
from app.utils.texts import format_rub


class NotificationService:
    """Encapsulate outgoing Telegram notifications."""

    async def send_subscription_created(
        self,
        bot: Bot,
        chat_id: int,
        subscription: Subscription,
    ) -> None:
        """Send the first-time subscription creation message."""
        subscription_url = subscription_service.build_remote_profile_url(subscription)
        text = (
            "✅ <b>Ваша подписка создана</b>\n"
            "Скопируйте ссылку на неё ниже\n"
            "Нажмите кнопку меню, чтобы открыть меню\n\n"
            f"<code>{subscription_url}</code>"
        )
        await bot.send_message(
            chat_id,
            text,
            reply_markup=subscription_created_keyboard(),
        )

    async def send_subscription_copy_text(
        self,
        bot: Bot,
        chat_id: int,
        subscription: Subscription,
    ) -> None:
        """Send the raw subscription URL for easy copying."""
        subscription_url = subscription_service.build_remote_profile_url(subscription)
        await bot.send_message(
            chat_id,
            "📋 Ссылка на подписку:\n"
            f"<code>{subscription_url}</code>",
            reply_markup=subscription_created_keyboard(),
        )

    async def send_subscription_credentials(
        self,
        bot: Bot,
        chat_id: int,
        subscription: Subscription,
    ) -> None:
        """Send subscription URL, fallback VLESS link and QR code."""
        access_url = subscription.access_url or "Ссылка пока недоступна."
        subscription_url = subscription_service.build_remote_profile_url(subscription)
        server_name = xui_service.build_server_display_name(subscription.server)
        text = (
            "Подписка активна.\n\n"
            f"Сервер: <b>{server_name}</b>\n"
            f"Тариф: <b>{subscription.plan.name}</b>\n"
            f"Действует до: <b>{subscription.expires_at:%d.%m.%Y %H:%M}</b>\n\n"
            "Ссылка подписки для Happ/Hiddify:\n"
            f"<code>{subscription_url}</code>\n\n"
            "Запасной VLESS-конфиг:\n"
            f"<code>{access_url}</code>"
        )
        await bot.send_message(
            chat_id,
            text,
            reply_markup=subscription_access_keyboard(subscription_url=subscription_url),
        )

        qr_buffer = build_qr_code(subscription_url)
        await bot.send_photo(
            chat_id,
            BufferedInputFile(qr_buffer.getvalue(), filename="codexvpn-subscription-qr.png"),
            caption="QR-код для импорта подписки в Happ/Hiddify.",
        )

    async def send_codex_pass_reward(self, bot: Bot, reward: CodexPassReward) -> None:
        """Notify the referrer that a new Codex Pass reward has been unlocked."""
        reward_lines: list[str] = []
        if reward.reward_balance_rub > 0:
            reward_lines.append(f"💰 {format_rub(reward.reward_balance_rub)} на баланс")
        if reward.reward_days > 0:
            reward_lines.append(f"🔥 +{reward.reward_months} мес Codex VPN")

        details = "Награда сохранена и будет применена при следующей оплате или продлении."
        if reward.reward_balance_rub > 0 and reward.wallet_balance is not None:
            details = (
                f"Баланс уже пополнен.\n"
                f"Текущий баланс: <b>{format_rub(reward.wallet_balance)}</b>"
            )
        if reward.applied_to_active_subscription and reward.new_expires_at is not None:
            details = (
                "Награда уже добавлена к вашей активной подписке.\n"
                f"Новая дата окончания: <b>{reward.new_expires_at:%d.%m.%Y %H:%M}</b>"
            )
        elif reward.reward_days > 0 and reward.reward_balance_rub > 0 and reward.wallet_balance is not None:
            details += "\nНаграда по месяцам сохранена до следующей платной активации."

        text = (
            "🎉 Поздравляем!\n\n"
            f"Вы открыли Level {reward.level}\n\n"
            "Ваша награда:\n\n"
            f"{chr(10).join(reward_lines)}\n\n"
            f"👥 Активировано приглашений: <b>{reward.total_activated_referrals}</b>\n\n"
            f"{details}"
        )
        await bot.send_message(reward.referrer_telegram_id, text)


notification_service = NotificationService()
