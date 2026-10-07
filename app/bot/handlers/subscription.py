"""Handlers for active subscription management."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import main_menu_keyboard, subscription_access_keyboard
from app.bot.states.purchase import PurchaseState
from app.config.settings import get_settings
from app.models.user import User
from app.services.notification_service import notification_service
from app.services.server_service import server_service
from app.services.subscription_service import subscription_service
from app.services.xui_service import XUIError, xui_service
from app.utils.datetime import now_tz
from app.utils.texts import MENU_ACCOUNT, format_rub

router = Router(name="subscription")


async def _leave_temporary_input_state(state: FSMContext) -> None:
    """Close temporary input modes without erasing stored data."""
    current_state = await state.get_state()
    if current_state in {
        PurchaseState.waiting_promocode.state,
        PurchaseState.waiting_topup_amount.state,
    }:
        await state.set_state(None)


def _format_remaining(delta: timedelta) -> str:
    """Format remaining subscription time in a user-friendly form."""
    total_seconds = max(int(delta.total_seconds()), 0)
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days} д. {hours} ч."
    if hours > 0:
        return f"{hours} ч. {minutes} мин."
    return f"{minutes} мин."


def _build_account_text(subscription, bonus_days_balance: int, wallet_balance: Decimal, traffic_text: str) -> str:
    """Build a richer personal account card."""
    now = now_tz()
    remaining = subscription.expires_at - now
    remaining_text = _format_remaining(remaining)
    status_emoji = "🟢" if remaining.total_seconds() > 0 else "🔴"
    bonus_text = (
        f"\n🎁 Бонус на балансе: <b>{bonus_days_balance} дн.</b>"
        if bonus_days_balance > 0
        else ""
    )
    server_name = xui_service.build_server_display_name(subscription.server)
    return (
        "👤 Личный кабинет\n\n"
        f"{status_emoji} Статус: <b>Подписка активна</b>\n"
        f"💰 Баланс: <b>{format_rub(wallet_balance)}</b>\n"
        f"📦 Тариф: <b>{subscription.plan.name}</b>\n"
        f"💳 Стоимость: <b>{format_rub(subscription.plan.price_amount)}</b>\n"
        f"🌍 Сервер: <b>{server_name}</b>\n"
        f"📅 Начало: <b>{subscription.starts_at:%d.%m.%Y %H:%M}</b>\n"
        f"⏳ Осталось: <b>{remaining_text}</b>\n"
        f"🕒 Действует до: <b>{subscription.expires_at:%d.%m.%Y %H:%M}</b>"
        f"{traffic_text}"
        f"{bonus_text}\n\n"
        "Ниже ваши данные для подключения:"
    )


async def _send_subscription_card(
    message: Message,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Render the personal account screen."""
    subscription = await subscription_service.get_active_for_user(session, current_user.id)
    wallet_balance = Decimal(current_user.wallet_balance or Decimal("0.00"))
    if subscription is None:
        bonus_line = (
            f"\n🎁 Бонус на балансе: <b>{current_user.bonus_days_balance} дн.</b>"
            if current_user.bonus_days_balance > 0
            else ""
        )
        no_access_text = (
            "👤 Личный кабинет\n\n"
            f"💰 Баланс: <b>{format_rub(wallet_balance)}</b>\n"
        )
        if current_user.free_subscription_claimed:
            no_access_text += (
                "Бесплатная подписка израсходована или закончилась.\n"
                "Оплатите VPN с помощью баланса или купите подписку по кнопке «Купить подписку»."
            )
        else:
            no_access_text += (
                "У вас пока нет активной подписки.\n"
                "Нажмите «Купить подписку», чтобы выбрать тариф и подключиться."
            )
        await message.answer(
            f"{no_access_text}{bonus_line}",
            reply_markup=main_menu_keyboard(),
        )
        return

    await session.refresh(subscription, attribute_names=["server", "plan"])
    access_url = subscription.access_url or "Ссылка пока недоступна."
    subscription_url = subscription_service.build_remote_profile_url(subscription)
    settings = get_settings()
    traffic_text = ""
    if subscription.plan.traffic_limit_gb:
        traffic_text = f"\n↕️ Трафик: <b>0 ГБ/{subscription.plan.traffic_limit_gb} ГБ</b>"
        try:
            traffic = await xui_service.get_client_traffic(subscription.server, subscription.client_email)
        except XUIError:
            traffic = None
        if traffic is not None:
            used_gb = (traffic[0] + traffic[1]) / (1024 * 1024 * 1024)
            used_rendered = f"{used_gb:.1f}".rstrip("0").rstrip(".")
            traffic_text = f"\n↕️ Трафик: <b>{used_rendered} ГБ/{subscription.plan.traffic_limit_gb} ГБ</b>"
    await message.answer(
        _build_account_text(subscription, current_user.bonus_days_balance, wallet_balance, traffic_text),
        reply_markup=subscription_access_keyboard(
            subscription_url=subscription_url,
            support_url=settings.telegram_support_url or None,
        ),
    )
    await message.answer(
        "Ссылка подписки для Happ/Hiddify:\n"
        f"<code>{subscription_url}</code>\n\n"
        "Запасной VLESS-конфиг:\n"
        f"<code>{access_url}</code>",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == MENU_ACCOUNT)
async def show_subscription(
    message: Message,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
) -> None:
    """Show current subscription details in the personal account."""
    await _leave_temporary_input_state(state)
    await _send_subscription_card(message, session, current_user)


@router.callback_query(F.data == "menu:account")
async def show_subscription_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
) -> None:
    """Show the personal account from an inline button."""
    if callback.message is None:
        await callback.answer()
        return

    await _leave_temporary_input_state(state)
    await _send_subscription_card(callback.message, session, current_user)
    await callback.answer()


@router.callback_query(F.data == "subscription:copy")
async def copy_subscription_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    current_user: User,
    bot,
) -> None:
    """Send the subscription URL in a copy-friendly format."""
    if callback.message is None:
        await callback.answer()
        return

    subscription = await subscription_service.get_active_for_user(session, current_user.id)
    if subscription is None:
        await callback.answer("Активная подписка не найдена.", show_alert=True)
        return

    await session.refresh(subscription, attribute_names=["server", "plan"])
    await notification_service.send_subscription_copy_text(bot, callback.message.chat.id, subscription)
    await callback.answer("Ссылка отправлена.")


@router.callback_query(F.data.startswith("switch:"))
async def switch_server_handler(
    callback: CallbackQuery,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Keep server switching available by callback if needed by future UI."""
    if not callback.data or callback.message is None:
        await callback.answer()
        return

    target_server_id = callback.data.split(":", maxsplit=1)[1]
    subscription = await subscription_service.get_active_for_user(session, current_user.id)
    if subscription is None:
        await callback.answer("Активная подписка не найдена.", show_alert=True)
        return

    target_server = await server_service.get_by_id(session, target_server_id)
    if target_server is None or not target_server.is_active:
        await callback.answer("Сервер недоступен.", show_alert=True)
        return

    await subscription_service.switch_server(session, subscription, target_server)
    await session.refresh(subscription, attribute_names=["server", "plan"])
    access_url = subscription.access_url or "Ссылка пока недоступна."
    subscription_url = subscription_service.build_remote_profile_url(subscription)
    settings = get_settings()
    await callback.message.answer(
        "⚙️ Сервер обновлён.\n\n"
        f"Новый сервер: <b>{xui_service.build_server_display_name(subscription.server)}</b>\n"
        f"Подписка действует до: <b>{subscription.expires_at:%d.%m.%Y %H:%M}</b>",
        reply_markup=subscription_access_keyboard(
            subscription_url=subscription_url,
            support_url=settings.telegram_support_url or None,
        ),
    )
    await callback.message.answer(
        "Ссылка подписки для Happ/Hiddify:\n"
        f"<code>{subscription_url}</code>\n\n"
        "Запасной VLESS-конфиг:\n"
        f"<code>{access_url}</code>",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer("Сервер обновлён.")
