"""Handlers for promocode application."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.common import (
    codex_pass_message,
    command_start,
    documents_message,
    send_main_menu,
    support_message,
)
from app.bot.handlers.purchase import choose_plan_to_buy, choose_plan_to_renew
from app.bot.handlers.subscription import show_subscription
from app.bot.keyboards.inline import promocode_input_keyboard
from app.bot.states.purchase import PurchaseState
from app.models.user import User
from app.services.notification_service import notification_service
from app.services.promocode_service import promocode_service
from app.services.subscription_service import subscription_service
from app.utils.texts import (
    MENU_ACCOUNT,
    MENU_BUY,
    MENU_CODEX_PASS,
    MENU_PROMOCODE,
    MENU_PROMOCODE_CANCEL,
    MENU_RENEW,
    MENU_SUPPORT,
    MENU_USAGE_TERMS,
)

router = Router(name="promo")

PROMOCODE_CANCEL_WORDS = {
    "отмена",
    "cancel",
    "назад",
    MENU_PROMOCODE_CANCEL.lower(),
}
PROMOCODE_EXIT_TEXTS = {
    "Меню",
    MENU_BUY,
    MENU_RENEW,
    MENU_ACCOUNT,
    MENU_CODEX_PASS,
    MENU_USAGE_TERMS,
    MENU_SUPPORT,
    MENU_PROMOCODE,
}


@router.message(F.text == MENU_PROMOCODE)
@router.callback_query(F.data == "menu:promocode")
async def prompt_promocode(message: Message | CallbackQuery, state: FSMContext) -> None:
    """Ask the user for a promocode."""
    await state.clear()
    await state.set_state(PurchaseState.waiting_promocode)

    text = (
        "Отправьте промокод одним сообщением.\n"
        "Или нажмите кнопку ниже, чтобы отменить ввод."
    )
    if isinstance(message, CallbackQuery):
        if message.message is None:
            await message.answer()
            return
        await message.message.answer(text, reply_markup=promocode_input_keyboard())
        await message.answer()
        return

    await message.answer(text, reply_markup=promocode_input_keyboard())


@router.callback_query(PurchaseState.waiting_promocode, F.data == "promo:cancel")
async def cancel_promocode_from_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel promocode input from the inline button."""
    await state.clear()
    if callback.message is not None:
        await send_main_menu(callback.message, "Ввод промокода отменён.")
    await callback.answer()


@router.message(PurchaseState.waiting_promocode, CommandStart())
async def restart_during_promocode_input(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Leave promocode mode and handle /start immediately."""
    await state.clear()
    await command_start(message, command, session, current_user, state, bot)


@router.message(PurchaseState.waiting_promocode, Command("menu"))
async def show_menu_during_promocode_input(message: Message, state: FSMContext) -> None:
    """Leave promocode mode and reopen the main menu."""
    await state.clear()
    await send_main_menu(message)


@router.message(PurchaseState.waiting_promocode, F.text.in_(PROMOCODE_EXIT_TEXTS))
async def exit_promocode_input_via_menu(
    message: Message,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
    bot: Bot,
) -> None:
    """Allow text menu actions to work while promocode input is active."""
    await state.clear()

    if message.text == MENU_BUY:
        await choose_plan_to_buy(message, session, state)
        return
    if message.text == MENU_RENEW:
        await choose_plan_to_renew(message, session, state)
        return
    if message.text == MENU_ACCOUNT:
        await show_subscription(message, session, current_user, state)
        return
    if message.text == MENU_CODEX_PASS:
        await codex_pass_message(message, bot, session, current_user, state)
        return
    if message.text == MENU_USAGE_TERMS:
        await documents_message(message, state)
        return
    if message.text == MENU_SUPPORT:
        await support_message(message, state)
        return
    if message.text == MENU_PROMOCODE:
        await prompt_promocode(message, state)
        return

    await send_main_menu(message)


@router.message(PurchaseState.waiting_promocode, F.text)
async def save_promocode(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    current_user: User,
    bot: Bot,
) -> None:
    """Validate and apply the user's promocode."""
    text = (message.text or "").strip()
    if not text:
        await message.answer("Нужен текстовый промокод.", reply_markup=promocode_input_keyboard())
        return

    if text.startswith("/"):
        await state.clear()
        await send_main_menu(
            message,
            "Ввод промокода отменён.\nКоманда не была зачтена как промокод, можете повторить её ещё раз.",
        )
        return

    if text.lower() in PROMOCODE_CANCEL_WORDS:
        await state.clear()
        await send_main_menu(message, "Ввод промокода отменён.")
        return

    promo = await promocode_service.get_active(session, text)
    if promo is None:
        await message.answer(
            "Промокод не найден, истёк или уже закончился.\n"
            "Проверьте код или нажмите «Отменить ввод промокода».",
            reply_markup=promocode_input_keyboard(),
        )
        return

    if promo.bonus_days > 0:
        try:
            subscription, created_new = await subscription_service.activate_promocode_access(
                session,
                current_user,
                promo.bonus_days,
                promocode_code=promo.code,
            )
        except RuntimeError:
            await state.clear()
            await send_main_menu(
                message,
                "Сейчас не удалось выдать доступ по промокоду. Попробуйте чуть позже.",
            )
            return

        await promocode_service.mark_used(session, promo)
        await state.clear()
        await send_main_menu(
            message,
            "Промокод успешно введён✅\n"
            f"Добавлено <b>{promo.bonus_days}</b> дней к вашей подписке",
        )
        if created_new:
            await session.refresh(subscription, attribute_names=["server", "plan"])
            await notification_service.send_subscription_credentials(
                bot,
                message.chat.id,
                subscription,
            )
        return

    await state.update_data(promocode_code=promo.code)
    await state.set_state(None)
    await send_main_menu(
        message,
        f"Промокод <b>{promo.code}</b> сохранён.\n"
        "Скидка будет применена к следующей оплате.",
    )
