"""General-purpose command and menu handlers."""

from __future__ import annotations

from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import documents_keyboard, main_menu_keyboard, support_keyboard
from app.bot.states.purchase import PurchaseState
from app.config.settings import get_settings
from app.models.user import User
from app.services.notification_service import notification_service
from app.services.referral_service import referral_service
from app.services.subscription_service import subscription_service
from app.utils.texts import (
    MAIN_MENU_TEXT,
    MENU_CODEX_PASS,
    MENU_SUPPORT,
    MENU_USAGE_TERMS,
    format_friends,
    format_months,
    format_rub,
)

router = Router(name="common")


async def _leave_temporary_input_state(state: FSMContext) -> None:
    """Close temporary input modes without erasing stored data."""
    current_state = await state.get_state()
    if current_state in {
        PurchaseState.waiting_promocode.state,
        PurchaseState.waiting_topup_amount.state,
    }:
        await state.set_state(None)


async def send_main_menu(message: Message, text: str = MAIN_MENU_TEXT) -> None:
    """Send the main inline menu."""
    await message.answer(text, reply_markup=main_menu_keyboard())


def _format_codex_reward(next_reward_balance_rub: Decimal | None, next_reward_months: int | None) -> str:
    """Render the next Codex Pass reward label."""
    if next_reward_balance_rub is not None and next_reward_balance_rub > 0:
        return f"💰 {format_rub(next_reward_balance_rub)} на баланс"
    return f"🎁 {format_months(next_reward_months or 0)} VPN бесплатно"


def _build_codex_pass_text(link: str, current_user: User, status) -> str:
    """Render the Codex Pass card."""
    if status.completed:
        return (
            "🔥 Codex Pass\n"
            f"Ваш уровень: Level {status.display_level}\n\n"
            "Все награды уже открыты.\n\n"
            f"{status.progress_bar} 100%\n\n"
            "🎁 Все награды Codex Pass уже получены\n\n"
            "👥 Мои приглашения:\n"
            f"{status.activated_referrals} друзей активировали VPN\n\n"
            f"🔗 Ваша ссылка:\n{link}"
        )

    return (
        "🔥 Codex Pass\n"
        f"Ваш уровень: Level {status.display_level}\n\n"
        "До следующей награды:\n\n"
        f"{status.progress_bar} {status.progress_percent}%\n\n"
        f"Пригласите ещё {format_friends(status.invites_to_next_reward)}\n\n"
        "и получите:\n"
        f"{_format_codex_reward(status.next_reward_balance_rub, status.next_reward_months)}\n\n"
        "👥 Мои приглашения:\n"
        f"{status.activated_referrals} друзей активировали VPN\n\n"
        f"Ваш код: <code>{current_user.referral_code}</code>\n"
        f"🔗 Ваша ссылка:\n{link}"
    )


@router.message(CommandStart())
async def command_start(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Handle /start, including referral deep links and first free subscription creation."""
    await state.clear()
    if command.args:
        await referral_service.attach_by_code(session, current_user, command.args)

    subscription = await subscription_service.get_active_for_user(session, current_user.id)
    if subscription is None and not current_user.free_subscription_claimed:
        await message.answer("Создаём ключ...")
        try:
            subscription = await subscription_service.activate_free_subscription(session, current_user)
        except RuntimeError:
            await send_main_menu(message, "Сейчас не удалось создать бесплатную подписку. Попробуйте ещё раз чуть позже.")
            return
        await session.refresh(subscription, attribute_names=["server", "plan"])
        await notification_service.send_subscription_created(bot, message.chat.id, subscription)
        return

    await send_main_menu(message)


@router.message(Command("menu"))
@router.message(F.text == "Меню")
async def command_menu(message: Message, state: FSMContext) -> None:
    """Show the main menu again."""
    await _leave_temporary_input_state(state)
    await send_main_menu(message)


@router.callback_query(F.data == "menu:home")
async def menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Show the main menu from an inline button."""
    if callback.message is None:
        await callback.answer()
        return

    await _leave_temporary_input_state(state)
    await send_main_menu(callback.message)
    await callback.answer()


@router.message(F.text == MENU_SUPPORT)
async def support_message(message: Message, state: FSMContext) -> None:
    """Send the support link."""
    await _leave_temporary_input_state(state)
    settings = get_settings()
    await message.answer(
        "Если нужна помощь, нажмите кнопку ниже.",
        reply_markup=support_keyboard(settings.telegram_support_url),
    )


@router.callback_query(F.data == "menu:support")
async def support_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Send the support link from the inline menu."""
    if callback.message is None:
        await callback.answer()
        return

    await _leave_temporary_input_state(state)
    settings = get_settings()
    await callback.message.answer(
        "Если нужна помощь, нажмите кнопку ниже.",
        reply_markup=support_keyboard(settings.telegram_support_url),
    )
    await callback.answer()


@router.message(F.text == MENU_USAGE_TERMS)
async def documents_message(message: Message, state: FSMContext) -> None:
    """Show permanent links to legal documents."""
    await _leave_temporary_input_state(state)
    settings = get_settings()
    text = (
        "Здесь собраны документы, которые доступны пользователю в любой момент:\n\n"
        "• Политика конфиденциальности\n"
        "• Пользовательское соглашение"
    )
    await message.answer(
        text,
        reply_markup=documents_keyboard(
            privacy_policy_url=settings.privacy_policy_url,
            terms_of_service_url=settings.terms_of_service_url,
        ),
    )


@router.callback_query(F.data == "menu:documents")
async def documents_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Show legal documents from the inline menu."""
    if callback.message is None:
        await callback.answer()
        return

    await _leave_temporary_input_state(state)
    settings = get_settings()
    text = (
        "Здесь собраны документы, которые доступны пользователю в любой момент:\n\n"
        "• Политика конфиденциальности\n"
        "• Пользовательское соглашение"
    )
    await callback.message.answer(
        text,
        reply_markup=documents_keyboard(
            privacy_policy_url=settings.privacy_policy_url,
            terms_of_service_url=settings.terms_of_service_url,
        ),
    )
    await callback.answer()


@router.message(F.text == MENU_CODEX_PASS)
async def codex_pass_message(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
) -> None:
    """Show the user's Codex Pass progress and referral link."""
    await _leave_temporary_input_state(state)
    me = await bot.get_me()
    username = me.username or "your_bot"
    link = f"https://t.me/{username}?start={current_user.referral_code}"
    status = await referral_service.get_codex_pass_status(session, current_user)
    await message.answer(_build_codex_pass_text(link, current_user, status), reply_markup=main_menu_keyboard())


@router.callback_query(F.data == "menu:codexpass")
async def codex_pass_callback(
    callback: CallbackQuery,
    bot: Bot,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
) -> None:
    """Show the user's Codex Pass progress from the inline menu."""
    if callback.message is None:
        await callback.answer()
        return

    await _leave_temporary_input_state(state)
    me = await bot.get_me()
    username = me.username or "your_bot"
    link = f"https://t.me/{username}?start={current_user.referral_code}"
    status = await referral_service.get_codex_pass_status(session, current_user)
    await callback.message.answer(
        _build_codex_pass_text(link, current_user, status),
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()
