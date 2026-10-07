"""Reusable text templates for the bot UI."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


MAIN_MENU_TEXT = (
    "Добро пожаловать в Codex VPN.\n\n"
    "Выберите действие ниже."
)

MENU_BUY = "Купить подписку"
MENU_RENEW = "Продлить"
MENU_ACCOUNT = "Личный кабинет"
MENU_TOPUP = "Пополнить баланс"
MENU_PROMOCODE = "Промокод"
MENU_PROMOCODE_CANCEL = "Отменить ввод промокода"
MENU_CODEX_PASS = "🔥 Codex Pass"
MENU_USAGE_TERMS = "Условия использования"
MENU_SUPPORT = "Поддержка"


def plural_ru(value: int, one: str, few: str, many: str) -> str:
    """Return the correct Russian plural form for a number."""
    remainder_100 = value % 100
    remainder_10 = value % 10
    if 11 <= remainder_100 <= 14:
        return many
    if remainder_10 == 1:
        return one
    if 2 <= remainder_10 <= 4:
        return few
    return many


def format_months(months: int) -> str:
    """Format a month amount in Russian."""
    return f"{months} {plural_ru(months, 'месяц', 'месяца', 'месяцев')}"


def format_friends(count: int) -> str:
    """Format a friend/invite amount in Russian."""
    return f"{count} {plural_ru(count, 'друга', 'друзей', 'друзей')}"


def format_rub(amount: Decimal | int | float | str) -> str:
    """Format a money amount in rubles for the UI."""
    decimal_amount = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rendered = f"{decimal_amount:.2f}".replace(".", ",")
    if rendered.endswith(",00"):
        rendered = rendered[:-3]
    return f"{rendered} ₽"


def format_balance_topup_success(amount: Decimal | int | float | str, balance: Decimal | int | float | str) -> str:
    """Build a standard success message for balance top-ups."""
    return (
        "Баланс успешно пополнен ✅\n"
        f"Зачислено: <b>{format_rub(amount)}</b>\n"
        f"Текущий баланс: <b>{format_rub(balance)}</b>"
    )


def render_progress_bar(percent: int, total_slots: int = 12) -> str:
    """Render a text progress bar."""
    normalized = max(0, min(percent, 100))
    filled = round(total_slots * normalized / 100)
    return f"{'█' * filled}{'░' * (total_slots - filled)}"
