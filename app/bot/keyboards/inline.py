"""Inline keyboards used by bot handlers."""

from __future__ import annotations

from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.plan import Plan
from app.models.vpn_server import VpnServer
from app.utils.texts import format_rub

HOME_CALLBACK = "menu:home"


def _home_row() -> list[InlineKeyboardButton]:
    """Build a standard row that returns the user to the main menu."""
    return [InlineKeyboardButton(text="🏠 Главное меню", callback_data=HOME_CALLBACK)]


def _terms_row() -> list[InlineKeyboardButton]:
    """Build a standard row that opens the usage terms screen."""
    return [InlineKeyboardButton(text="📄 Условия использования", callback_data="menu:documents")]


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the main inline menu shown in bot messages."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🛒 Купить подписку", callback_data="menu:buy"),
                InlineKeyboardButton(text="🔄 Продлить", callback_data="menu:renew"),
            ],
            [
                InlineKeyboardButton(text="👤 Личный кабинет", callback_data="menu:account"),
                InlineKeyboardButton(text="💰 Пополнить баланс", callback_data="menu:topup"),
            ],
            [
                InlineKeyboardButton(text="🎟 Промокод", callback_data="menu:promocode"),
                InlineKeyboardButton(text="🔥 Codex Pass", callback_data="menu:codexpass"),
            ],
            [InlineKeyboardButton(text="📄 Условия использования", callback_data="menu:documents")],
            [InlineKeyboardButton(text="💬 Поддержка", callback_data="menu:support")],
        ]
    )


def promocode_input_keyboard() -> InlineKeyboardMarkup:
    """Build actions for promocode entry mode."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить ввод промокода", callback_data="promo:cancel")],
            _home_row(),
        ]
    )


def topup_options_keyboard(suggested_amounts: list[tuple[str, Decimal]]) -> InlineKeyboardMarkup:
    """Build suggested balance top-up amounts plus a custom amount action."""
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"💳 {label} · {format_rub(amount)}",
                callback_data=f"topup:preset:{amount}",
            )
        ]
        for label, amount in suggested_amounts
    ]
    rows.append([InlineKeyboardButton(text="✍️ Своя сумма", callback_data="topup:custom")])
    rows.append(_terms_row())
    rows.append(_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def topup_input_keyboard() -> InlineKeyboardMarkup:
    """Build actions for custom balance amount input."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить ввод суммы", callback_data="topup:cancel")],
            _terms_row(),
            _home_row(),
        ]
    )


def plans_keyboard(plans: list[Plan], renewal: bool = False) -> InlineKeyboardMarkup:
    """Build a plan selection keyboard."""
    prefix = "renew" if renewal else "buy"
    rows = [
        [
            InlineKeyboardButton(
                text=f"💳 {plan.name} - {format_rub(plan.price_amount)}",
                callback_data=f"plan:{plan.id}:{prefix}",
            )
        ]
        for plan in plans
    ]
    rows.append(_terms_row())
    rows.append(_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_keyboard(
    plan_id: str,
    mode: str,
    *,
    can_pay_with_balance: bool,
) -> InlineKeyboardMarkup:
    """Build payment method choices for a selected tariff."""
    rows: list[list[InlineKeyboardButton]] = []
    if can_pay_with_balance:
        rows.append(
            [InlineKeyboardButton(text="💰 Оплатить с баланса", callback_data=f"paywithbalance:{plan_id}:{mode}")]
        )
    rows.append(
        [InlineKeyboardButton(text="💳 Оплатить через YooKassa", callback_data=f"paywithyookassa:{plan_id}:{mode}")]
    )
    rows.append([InlineKeyboardButton(text="➕ Пополнить баланс", callback_data="menu:topup")])
    rows.append(_terms_row())
    rows.append(_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def servers_keyboard(servers: list[VpnServer], action: str = "purchase") -> InlineKeyboardMarkup:
    """Build a server selection keyboard."""
    callback_prefix = "switch" if action == "switch" else "buyserver"
    rows = [
        [
            InlineKeyboardButton(
                text=f"🌍 {server.name}",
                callback_data=f"{callback_prefix}:{server.id}",
            )
        ]
        for server in servers
    ]
    rows.append(_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_access_keyboard(
    subscription_url: str | None = None,
    support_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Build quick actions for an active subscription."""
    first_row: list[InlineKeyboardButton] = []
    if subscription_url:
        first_row.append(InlineKeyboardButton(text="📋 Скопировать подписку", callback_data="subscription:copy"))
    first_row.append(InlineKeyboardButton(text="🔄 Продлить", callback_data="menu:renew"))

    rows = [first_row]
    if support_url:
        rows.append([InlineKeyboardButton(text="💬 Поддержка", url=support_url)])
    rows.append(_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_created_keyboard() -> InlineKeyboardMarkup:
    """Build buttons shown right after the first key is created."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Скопировать подписку", callback_data="subscription:copy")],
            _home_row(),
        ]
    )


def payment_url_keyboard(payment_url: str, payment_id: str) -> InlineKeyboardMarkup:
    """Build payment actions for YooKassa."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить через YooKassa", url=payment_url)],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"paycheck:{payment_id}")],
            _terms_row(),
            _home_row(),
        ]
    )


def documents_keyboard(privacy_policy_url: str, terms_of_service_url: str) -> InlineKeyboardMarkup:
    """Build buttons for compliance documents."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url=privacy_policy_url)],
            [InlineKeyboardButton(text="📘 Пользовательское соглашение", url=terms_of_service_url)],
            _home_row(),
        ]
    )


def support_keyboard(url: str) -> InlineKeyboardMarkup:
    """Build a support URL button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать в поддержку", url=url)],
            _home_row(),
        ]
    )


def channel_subscription_keyboard(url: str) -> InlineKeyboardMarkup:
    """Build a single button that opens the required Telegram channel."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📢 Канал", url=url)],
        ]
    )
