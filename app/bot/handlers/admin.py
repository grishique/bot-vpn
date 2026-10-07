"""Administrator command handlers."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.states.admin import AddServerState
from app.config.settings import get_settings
from app.models.enums import PaymentStatus, SubscriptionStatus, UserRole
from app.models.payment import Payment
from app.models.promocode import Promocode
from app.models.subscription import Subscription
from app.models.user import User
from app.models.vpn_server import VpnServer
from app.scheduler.tasks import broadcast_message_task
from app.services.promocode_service import promocode_service
from app.services.server_service import server_service
from app.services.user_service import user_service

router = Router(name="admin")


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


async def _ensure_admin(message: Message, current_user: User) -> bool:
    if _is_admin(current_user):
        return True
    await message.answer("Команда доступна только администраторам.")
    return False


async def _delayed_restart() -> None:
    await asyncio.sleep(1)
    os._exit(0)


def _format_promo_expiry(promo: Promocode) -> str:
    return promo.expires_at.strftime("%Y-%m-%d") if promo.expires_at else "never"


def _format_promo_reward(promo: Promocode) -> str:
    if promo.bonus_days:
        return f"+{promo.bonus_days}d"
    if promo.discount_percent is not None:
        return f"{promo.discount_percent}%"
    if promo.discount_amount is not None:
        return str(promo.discount_amount)
    return "none"


@router.message(Command("stats"))
async def admin_stats(message: Message, session: AsyncSession, current_user: User) -> None:
    """Show dashboard metrics for administrators."""
    if not await _ensure_admin(message, current_user):
        return

    user_stats = await user_service.get_stats(session)
    active_subscriptions = await session.scalar(
        select(func.count()).select_from(Subscription).where(Subscription.status == SubscriptionStatus.ACTIVE)
    )
    total_servers = await session.scalar(select(func.count()).select_from(VpnServer))
    total_revenue = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount_total), 0)).where(Payment.status == PaymentStatus.PAID)
    )
    await message.answer(
        "Статистика:\n"
        f"Пользователей: <b>{user_stats['total_users']}</b>\n"
        f"Админов: <b>{user_stats['admin_users']}</b>\n"
        f"Заблокировано: <b>{user_stats['banned_users']}</b>\n"
        f"Активных подписок: <b>{int(active_subscriptions or 0)}</b>\n"
        f"Серверов: <b>{int(total_servers or 0)}</b>\n"
        f"Выручка: <b>{total_revenue}</b>"
    )


@router.message(Command("users"))
async def admin_users(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
) -> None:
    """List users page by page."""
    if not await _ensure_admin(message, current_user):
        return

    page = 1
    if command.args:
        try:
            page = max(int(command.args), 1)
        except ValueError:
            page = 1

    limit = 20
    users = await user_service.list_users(session, limit=limit, offset=(page - 1) * limit)
    if not users:
        await message.answer("Список пользователей пуст.")
        return

    lines = [f"Пользователи, страница {page}:"]
    for user in users:
        lines.append(
            f"{user.telegram_id} | @{user.username or '-'} | banned={user.is_banned} | role={user.role}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("user"))
async def admin_user_info(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Show detailed information about a specific user."""
    if not await _ensure_admin(message, current_user):
        return
    if not command.args:
        await message.answer("Использование: /user <telegram_id>")
        return

    try:
        telegram_id = int(command.args.strip())
    except ValueError:
        await message.answer("Telegram ID должен быть числом.")
        return

    user = await user_service.get_by_telegram_id(session, telegram_id)
    if user is None:
        await message.answer("Пользователь не найден.")
        return

    subscription = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    latest_subscription = subscription.scalar_one_or_none()
    text = (
        f"Пользователь: <b>{user.telegram_id}</b>\n"
        f"Username: @{user.username or '-'}\n"
        f"Role: {user.role}\n"
        f"Banned: {user.is_banned}\n"
        f"Referral code: <code>{user.referral_code}</code>\n"
        f"Bonus days: {user.bonus_days_balance}"
    )
    if latest_subscription is not None:
        text += (
            f"\nПоследняя подписка: {latest_subscription.status}"
            f"\nИстекает: {latest_subscription.expires_at:%d.%m.%Y %H:%M}"
        )
    await message.answer(text)


@router.message(Command("ban"))
async def admin_ban(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Ban a user by Telegram id."""
    if not await _ensure_admin(message, current_user):
        return
    if not command.args:
        await message.answer("Использование: /ban <telegram_id>")
        return

    try:
        telegram_id = int(command.args.strip())
    except ValueError:
        await message.answer("Telegram ID должен быть числом.")
        return

    user = await user_service.get_by_telegram_id(session, telegram_id)
    if user is None:
        await message.answer("Пользователь не найден.")
        return

    await user_service.ban_user(session, user)
    await message.answer(f"Пользователь {telegram_id} заблокирован.")


@router.message(Command("unban"))
async def admin_unban(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Unban a user by Telegram id."""
    if not await _ensure_admin(message, current_user):
        return
    if not command.args:
        await message.answer("Использование: /unban <telegram_id>")
        return

    try:
        telegram_id = int(command.args.strip())
    except ValueError:
        await message.answer("Telegram ID должен быть числом.")
        return

    user = await user_service.get_by_telegram_id(session, telegram_id)
    if user is None:
        await message.answer("Пользователь не найден.")
        return

    await user_service.unban_user(session, user)
    await message.answer(f"Пользователь {telegram_id} разблокирован.")


@router.message(Command("broadcast"))
async def admin_broadcast(
    message: Message,
    command: CommandObject,
    current_user: User,
) -> None:
    """Send a broadcast message via Celery."""
    if not await _ensure_admin(message, current_user):
        return
    if not command.args:
        await message.answer("Использование: /broadcast <текст сообщения>")
        return

    broadcast_message_task.delay(command.args.strip())
    await message.answer("Рассылка поставлена в очередь.")


@router.message(Command("restart"))
async def admin_restart(message: Message, current_user: User) -> None:
    """Restart the app container by exiting the process."""
    if not await _ensure_admin(message, current_user):
        return
    await message.answer("Перезапускаю приложение.")
    asyncio.create_task(_delayed_restart())


@router.message(Command("addserver"))
async def admin_addserver_start(
    message: Message,
    state: FSMContext,
    current_user: User,
) -> None:
    """Start the add-server wizard."""
    if not await _ensure_admin(message, current_user):
        return
    await state.set_state(AddServerState.name)
    await message.answer("Введите имя сервера.")


@router.message(Command("cancel"))
async def admin_cancel(message: Message, state: FSMContext, current_user: User) -> None:
    """Cancel the current admin wizard."""
    if not await _ensure_admin(message, current_user):
        return
    await state.clear()
    await message.answer("Текущий сценарий отменен.")


@router.message(AddServerState.name)
async def addserver_name(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(name=(message.text or "").strip())
    await state.set_state(AddServerState.panel_url)
    await message.answer("Введите URL панели 3x-ui, например https://panel.example.com/")


@router.message(AddServerState.panel_url)
async def addserver_panel_url(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(panel_url=(message.text or "").strip())
    await state.set_state(AddServerState.panel_username)
    await message.answer("Введите логин панели.")


@router.message(AddServerState.panel_username)
async def addserver_panel_username(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(panel_username=(message.text or "").strip())
    await state.set_state(AddServerState.panel_password)
    await message.answer("Введите пароль панели.")


@router.message(AddServerState.panel_password)
async def addserver_panel_password(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(panel_password=(message.text or "").strip())
    await state.set_state(AddServerState.inbound_id)
    await message.answer("Введите inbound ID из 3x-ui.")


@router.message(AddServerState.inbound_id)
async def addserver_inbound_id(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    try:
        inbound_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("Inbound ID должен быть числом.")
        return
    await state.update_data(inbound_id=inbound_id)
    await state.set_state(AddServerState.host)
    await message.answer("Введите публичный host/IP для VLESS ссылки.")


@router.message(AddServerState.host)
async def addserver_host(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(host=(message.text or "").strip())
    await state.set_state(AddServerState.port)
    await message.answer("Введите публичный порт.")


@router.message(AddServerState.port)
async def addserver_port(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    try:
        port = int((message.text or "").strip())
    except ValueError:
        await message.answer("Порт должен быть числом.")
        return
    await state.update_data(port=port)
    await state.set_state(AddServerState.public_key)
    await message.answer("Введите Reality public key.")


@router.message(AddServerState.public_key)
async def addserver_public_key(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(public_key=(message.text or "").strip())
    await state.set_state(AddServerState.sni)
    await message.answer("Введите SNI.")


@router.message(AddServerState.sni)
async def addserver_sni(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(sni=(message.text or "").strip())
    await state.set_state(AddServerState.short_id)
    await message.answer("Введите short ID.")


@router.message(AddServerState.short_id)
async def addserver_short_id(message: Message, state: FSMContext, current_user: User) -> None:
    if not await _ensure_admin(message, current_user):
        return
    await state.update_data(short_id=(message.text or "").strip())
    await state.set_state(AddServerState.advanced)
    await message.answer(
        "Введите расширенные параметры в формате "
        "fingerprint|spider_x|flow|transport|remark_prefix|sort_order\n"
        "Или отправьте <code>default</code> для стандартных значений."
    )


@router.message(AddServerState.advanced)
async def addserver_finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Finish the add-server wizard and persist the server."""
    if not await _ensure_admin(message, current_user):
        return

    data = await state.get_data()
    advanced = (message.text or "default").strip()
    fingerprint = "chrome"
    spider_x = "/"
    flow = "xtls-rprx-vision"
    transport = "tcp"
    remark_prefix = "vpn"
    sort_order = 100

    if advanced.lower() != "default":
        parts = [part.strip() for part in advanced.split("|")]
        if len(parts) != 6:
            await message.answer("Нужно 6 значений через | или слово default.")
            return
        fingerprint, spider_x, flow, transport, remark_prefix, sort_order_text = parts
        try:
            sort_order = int(sort_order_text)
        except ValueError:
            await message.answer("sort_order должен быть числом.")
            return

    server = await server_service.add_server(
        session,
        name=data["name"],
        panel_url=data["panel_url"],
        panel_username=data["panel_username"],
        panel_password=data["panel_password"],
        inbound_id=data["inbound_id"],
        host=data["host"],
        port=data["port"],
        public_key=data["public_key"],
        sni=data["sni"],
        short_id=data["short_id"],
        fingerprint=fingerprint,
        spider_x=spider_x,
        flow=flow,
        transport=transport,
        remark_prefix=remark_prefix,
        sort_order=sort_order,
    )
    await state.clear()
    await message.answer(f"Сервер добавлен: <b>{server.name}</b>\nID: <code>{server.id}</code>")


@router.message(Command("removeserver"))
async def admin_removeserver(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Remove a configured server if it has no active subscriptions."""
    if not await _ensure_admin(message, current_user):
        return
    if not command.args:
        await message.answer("Использование: /removeserver <server_id>")
        return

    server = await server_service.get_by_id(session, command.args.strip())
    if server is None:
        await message.answer("Сервер не найден.")
        return

    active_count = await session.scalar(
        select(func.count())
        .select_from(Subscription)
        .where(
            Subscription.server_id == server.id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
    )
    if int(active_count or 0) > 0:
        await message.answer("На сервере есть активные подписки. Сначала перенесите или завершите их.")
        return

    await server_service.remove_server(session, server)
    await message.answer(f"Сервер {server.name} удален.")

@router.message(Command("createpromocode"))
async def admin_create_promocode(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
) -> None:
    """Create a promocode that adds subscription days."""
    if not await _ensure_admin(message, current_user):
        return

    if not command.args:
        await message.answer("\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: /createpromocode \"\u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434\u0430\" \"\u0434\u043d\u0438\" \"\u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u044f\"")
        return

    try:
        parts = shlex.split(command.args)
    except ValueError:
        await message.answer(
            "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0440\u0430\u0437\u043e\u0431\u0440\u0430\u0442\u044c \u0430\u0440\u0433\u0443\u043c\u0435\u043d\u0442\u044b. \u041f\u0440\u0438\u043c\u0435\u0440: /createpromocode \"CODEXFREE\" \"30\" \"5\""
        )
        return

    if len(parts) != 3:
        await message.answer(
            "\u041d\u0443\u0436\u043d\u043e \u043f\u0435\u0440\u0435\u0434\u0430\u0442\u044c 3 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u044f. \u041f\u0440\u0438\u043c\u0435\u0440: /createpromocode \"CODEXFREE\" \"30\" \"5\""
        )
        return

    try:
        bonus_days = int(parts[1])
        max_usages = int(parts[2])
    except ValueError:
        await message.answer("\u0414\u043d\u0438 \u0438 \u0447\u0438\u0441\u043b\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0439 \u0434\u043e\u043b\u0436\u043d\u044b \u0431\u044b\u0442\u044c \u0446\u0435\u043b\u044b\u043c\u0438 \u0447\u0438\u0441\u043b\u0430\u043c\u0438.")
        return

    if bonus_days <= 0 or max_usages <= 0:
        await message.answer("\u0414\u043d\u0438 \u0438 \u0447\u0438\u0441\u043b\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0439 \u0434\u043e\u043b\u0436\u043d\u044b \u0431\u044b\u0442\u044c \u0431\u043e\u043b\u044c\u0448\u0435 \u043d\u0443\u043b\u044f.")
        return

    raw_code = parts[0].strip()
    code = re.sub(r"\\s+", "-", raw_code).upper()
    if not code:
        await message.answer("\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434\u0430 \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u044b\u043c.")
        return
    if len(code) > 64:
        await message.answer("\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434\u0430 \u0441\u043b\u0438\u0448\u043a\u043e\u043c \u0434\u043b\u0438\u043d\u043d\u043e\u0435. \u041c\u0430\u043a\u0441\u0438\u043c\u0443\u043c 64 \u0441\u0438\u043c\u0432\u043e\u043b\u0430.")
        return
    if not re.fullmatch(r"[A-Z0-9_-]+", code):
        await message.answer("\u0412 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0438 \u043f\u0440\u043e\u043c\u043e\u043a\u043e\u0434\u0430 \u043c\u043e\u0436\u043d\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u044c \u0442\u043e\u043b\u044c\u043a\u043e \u0431\u0443\u043a\u0432\u044b, \u0446\u0438\u0444\u0440\u044b, \u0434\u0435\u0444\u0438\u0441 \u0438 _.")
        return

    existing = await session.scalar(select(Promocode.id).where(Promocode.code == code))
    if existing is not None:
        await message.answer(f"\u041f\u0440\u043e\u043c\u043e\u043a\u043e\u0434 <b>{code}</b> \u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442.")
        return

    promo = Promocode(
        code=code,
        description=f"Admin bonus promo: +{bonus_days} days",
        bonus_days=bonus_days,
        max_usages=max_usages,
        is_active=True,
        created_by_id=current_user.id,
    )
    session.add(promo)
    await session.flush()
    await message.answer(
        "\u041f\u0440\u043e\u043c\u043e\u043a\u043e\u0434 \u0441\u043e\u0437\u0434\u0430\u043d.\n\n"
        f"\u041a\u043e\u0434: <code>{promo.code}</code>\n"
        f"\u0414\u043e\u0431\u0430\u0432\u043b\u044f\u0435\u0442 \u043a \u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0435: <b>{promo.bonus_days}</b> \u0434\u043d.\n"
        f"\u0414\u043e\u0441\u0442\u0443\u043f\u043d\u043e \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0439: <b>{promo.max_usages}</b>"
    )



@router.message(Command("promocodes"))
async def admin_promocodes(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
) -> None:
    """List active promocodes or create a new one."""
    if not await _ensure_admin(message, current_user):
        return

    args = command.args or ""
    if args.startswith("create "):
        parts = args.split(maxsplit=5)
        if len(parts) < 5:
            await message.answer(
                "Использование: /promocodes create CODE DISCOUNT_PERCENT MAX_USES YYYY-MM-DD [описание]"
            )
            return

        _, code, discount_text, max_uses_text, expires_text, *description_tail = parts
        try:
            discount_percent = int(discount_text)
            max_uses = int(max_uses_text)
            expires_at = datetime.strptime(expires_text, "%Y-%m-%d").replace(
                tzinfo=ZoneInfo(get_settings().timezone)
            )
        except ValueError:
            await message.answer("Проверьте формат числа или даты YYYY-MM-DD.")
            return

        description = description_tail[0] if description_tail else "Telegram admin created promo"
        promo = Promocode(
            code=code.upper(),
            description=description,
            discount_percent=discount_percent,
            max_usages=max_uses,
            expires_at=expires_at,
            is_active=True,
            created_by_id=current_user.id,
        )
        session.add(promo)
        await session.flush()
        await message.answer(f"Промокод <b>{promo.code}</b> создан.")
        return

    result = await session.execute(
        select(Promocode).where(Promocode.is_active.is_(True)).order_by(Promocode.created_at.desc()).limit(20)
    )
    promos = result.scalars().all()
    if not promos:
        await message.answer("Активных промокодов нет.")
        return

    lines = ["Активные промокоды:"]
    for promo in promos:
        lines.append(
            f"{promo.code} | reward={_format_promo_reward(promo)} | "
            f"used={promo.used_count}/{promo.max_usages or 'inf'} | "
            f"expires={_format_promo_expiry(promo)}"
        )
    await message.answer("\n".join(lines))
