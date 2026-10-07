"""Handlers for plan selection, balance top-ups and payment creation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.inline import (
    payment_method_keyboard,
    payment_url_keyboard,
    plans_keyboard,
    topup_input_keyboard,
    topup_options_keyboard,
)
from app.bot.states.purchase import PurchaseState
from app.config.settings import get_settings
from app.models.enums import PaymentProvider, PaymentStatus
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.user import User
from app.services.notification_service import notification_service
from app.services.payment_service import PaymentActivationResult, payment_service
from app.services.promocode_service import promocode_service
from app.services.yookassa_service import yookassa_service
from app.utils.texts import (
    MENU_BUY,
    MENU_RENEW,
    MENU_TOPUP,
    format_balance_topup_success,
    format_rub,
)

router = Router(name="purchase")

SUGGESTED_TOPUP_LABELS = {
    30: "1 мес стандарт",
    90: "3 мес базовый",
    365: "12 мес оптимальный",
}
PAYMENT_TERMS_NOTICE = "Оформляя подписку, вы соглашаетесь с условиями использования бота."


async def _leave_temporary_input_state(state: FSMContext) -> None:
    """Close temporary input modes without erasing stored data."""
    current_state = await state.get_state()
    if current_state in {
        PurchaseState.waiting_promocode.state,
        PurchaseState.waiting_topup_amount.state,
    }:
        await state.set_state(None)


async def _load_active_plans(session: AsyncSession) -> list[Plan]:
    """Return active plans in the configured order."""
    result = await session.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order, Plan.duration_days)
    )
    return list(result.scalars().all())


def _parse_topup_amount(text: str) -> Decimal:
    """Parse a free-form RUB amount entered by the user."""
    cleaned = (
        text.strip()
        .replace("₽", "")
        .replace("руб", "")
        .replace("RUB", "")
        .replace("rub", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    amount = Decimal(cleaned)
    amount = amount.quantize(Decimal("0.01"))
    if amount < Decimal("100.00"):
        raise ValueError("Минимальная сумма пополнения — 100 ₽.")
    if amount > Decimal("100000.00"):
        raise ValueError("Слишком большая сумма. Введите до 100000 ₽.")
    return amount


async def _build_suggested_topups(session: AsyncSession) -> list[tuple[str, Decimal]]:
    """Return suggested top-up amounts based on active tariffs."""
    plans = await _load_active_plans(session)
    suggested: list[tuple[str, Decimal]] = []
    seen_amounts: set[Decimal] = set()
    for plan in plans:
        label = SUGGESTED_TOPUP_LABELS.get(plan.duration_days)
        if not label or plan.price_amount in seen_amounts:
            continue
        suggested.append((label, Decimal(plan.price_amount)))
        seen_amounts.add(Decimal(plan.price_amount))
    return suggested


async def _send_topup_menu(message: Message, session: AsyncSession, current_user: User) -> None:
    """Show suggested balance top-up amounts plus custom input."""
    suggested = await _build_suggested_topups(session)
    wallet_balance = Decimal(current_user.wallet_balance or Decimal("0.00"))
    text = (
        "💰 Пополнение баланса\n\n"
        f"Ваш текущий баланс: <b>{format_rub(wallet_balance)}</b>\n\n"
        "Выберите готовую сумму пополнения или нажмите «Своя сумма».\n\n"
        f"<i>{PAYMENT_TERMS_NOTICE}</i>"
    )
    await message.answer(text, reply_markup=topup_options_keyboard(suggested))


async def _send_topup_payment_invoice(message: Message, payment: Payment) -> None:
    """Open the selected top-up payment in the configured provider."""
    provider = PaymentProvider(get_settings().payment_provider)
    if provider == PaymentProvider.YOOKASSA:
        if not yookassa_service.is_configured():
            await message.answer("YooKassa ещё не настроена. Проверьте SHOP_ID, SECRET_KEY и RETURN_URL.")
            return

        try:
            yookassa_payment = await yookassa_service.create_payment(
                payment=payment,
                description="Пополнение баланса Codex VPN",
            )
        except httpx.HTTPError:
            await message.answer("Не удалось создать платёж в YooKassa. Попробуйте ещё раз чуть позже.")
            return

        payment.provider_payment_id = yookassa_payment.payment_id
        await message.answer(
            (
                "💰 Пополнение баланса\n"
                f"Сумма: <b>{format_rub(payment.amount_total)}</b>\n\n"
                f"<i>{PAYMENT_TERMS_NOTICE}</i>\n\n"
                "Откройте ссылку оплаты, а после оплаты нажмите «Проверить оплату»."
            ),
            reply_markup=payment_url_keyboard(yookassa_payment.confirmation_url, str(payment.id)),
        )
        return

    settings = get_settings()
    await message.answer_invoice(
        title="Пополнение баланса Codex VPN",
        description=f"Пополнение баланса на {format_rub(payment.amount_total)}",
        payload=payment.invoice_payload,
        provider_token=settings.telegram_provider_token,
        currency=payment.currency,
        prices=[LabeledPrice(label="Пополнение баланса", amount=payment.amount_minor)],
    )


async def _send_payment_result(
    message: Message,
    bot,
    chat_id: int,
    activation_result: PaymentActivationResult,
) -> None:
    """Send the correct success output depending on payment purpose."""
    settings = get_settings()

    if activation_result.balance_topup_amount is not None and activation_result.wallet_balance is not None:
        await message.answer(
            format_balance_topup_success(
                activation_result.balance_topup_amount,
                activation_result.wallet_balance,
            )
        )
        return

    await message.answer(settings.payment_success_text)

    if activation_result.codex_pass_reward is not None:
        await notification_service.send_codex_pass_reward(bot, activation_result.codex_pass_reward)

    if activation_result.subscription is not None:
        await notification_service.send_subscription_credentials(
            bot,
            chat_id,
            activation_result.subscription,
        )


@router.message(F.text == MENU_TOPUP)
@router.callback_query(F.data == "menu:topup")
async def prompt_balance_topup(
    event: Message | CallbackQuery,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
) -> None:
    """Show the balance top-up menu with preset amounts and a custom option."""
    await _leave_temporary_input_state(state)
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await _send_topup_menu(event.message, session, current_user)
        await event.answer()
        return

    await _send_topup_menu(event, session, current_user)


@router.callback_query(F.data == "topup:custom")
async def prompt_custom_topup_amount(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask the user to enter a custom balance top-up amount."""
    await state.set_state(PurchaseState.waiting_topup_amount)
    if callback.message is not None:
        await callback.message.answer(
            "Введите сумму пополнения одним сообщением.\n"
            "Например: <b>349</b> или <b>349.50</b>\n\n"
            f"<i>{PAYMENT_TERMS_NOTICE}</i>",
            reply_markup=topup_input_keyboard(),
        )
    await callback.answer()


@router.callback_query(PurchaseState.waiting_topup_amount, F.data == "topup:cancel")
async def cancel_custom_topup_amount(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel custom balance top-up amount entry."""
    await state.clear()
    if callback.message is not None:
        await callback.message.answer("Ввод суммы отменён.")
    await callback.answer()


@router.callback_query(F.data.startswith("topup:preset:"))
async def create_preset_topup_payment(
    callback: CallbackQuery,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
) -> None:
    """Create a balance top-up payment from a suggested amount button."""
    if callback.message is None or callback.data is None:
        await callback.answer()
        return

    await _leave_temporary_input_state(state)
    amount = Decimal(callback.data.split(":", maxsplit=2)[2]).quantize(Decimal("0.01"))
    payment = await payment_service.create_balance_topup_payment(session, current_user, amount)
    await _send_topup_payment_invoice(callback.message, payment)
    await callback.answer("Ссылка на оплату готова.")


@router.message(PurchaseState.waiting_topup_amount, F.text)
async def create_custom_topup_payment(
    message: Message,
    session: AsyncSession,
    current_user: User,
    state: FSMContext,
) -> None:
    """Create a balance top-up payment from a user-entered amount."""
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Ввод суммы отменён. Команда не была воспринята как сумма.")
        return

    if text.lower() in {"отмена", "cancel", "назад"}:
        await state.clear()
        await message.answer("Ввод суммы отменён.")
        return

    try:
        amount = _parse_topup_amount(text)
    except (InvalidOperation, ValueError) as exc:
        await message.answer(str(exc), reply_markup=topup_input_keyboard())
        return

    payment = await payment_service.create_balance_topup_payment(session, current_user, amount)
    await state.clear()
    await _send_topup_payment_invoice(message, payment)


@router.message(F.text == MENU_BUY)
@router.callback_query(F.data == "menu:buy")
async def choose_plan_to_buy(
    event: Message | CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Show plans for a new subscription."""
    await _leave_temporary_input_state(state)
    plans = await _load_active_plans(session)
    text = f"Выберите тариф для новой подписки.\n\n<i>{PAYMENT_TERMS_NOTICE}</i>"
    if not plans:
        text = "Тарифы пока не настроены."

    if isinstance(event, Message):
        await event.answer(text, reply_markup=plans_keyboard(plans, renewal=False) if plans else None)
    else:
        await event.message.answer(
            text,
            reply_markup=plans_keyboard(plans, renewal=False) if plans else None,
        )
        await event.answer()


@router.message(F.text == MENU_RENEW)
@router.callback_query(F.data == "menu:renew")
async def choose_plan_to_renew(
    event: Message | CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Show plans for renewal."""
    await _leave_temporary_input_state(state)
    plans = await _load_active_plans(session)
    text = f"Выберите тариф для продления.\n\n<i>{PAYMENT_TERMS_NOTICE}</i>"
    if not plans:
        text = "Тарифы пока не настроены."

    if isinstance(event, Message):
        await event.answer(text, reply_markup=plans_keyboard(plans, renewal=True) if plans else None)
    else:
        await event.message.answer(
            text,
            reply_markup=plans_keyboard(plans, renewal=True) if plans else None,
        )
        await event.answer()


@router.callback_query(F.data.startswith("plan:"))
async def create_invoice_for_plan(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    current_user: User,
) -> None:
    """Show payment methods immediately after the user chooses a plan."""
    if not callback.data or callback.message is None:
        await callback.answer()
        return

    _, plan_id, mode = callback.data.split(":")
    plan = await session.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return

    state_data = await state.get_data()
    promo = None
    promo_code = state_data.get("promocode_code")
    if promo_code:
        promo = await promocode_service.get_active(session, promo_code)

    charge = payment_service.get_plan_charge(plan, promo)
    wallet_balance = Decimal(current_user.wallet_balance or Decimal("0.00"))
    lines = [
        f"📦 Тариф: <b>{plan.name}</b>",
        f"💳 Стоимость: <b>{format_rub(charge.final_amount)}</b>",
        f"💰 Баланс: <b>{format_rub(wallet_balance)}</b>",
    ]
    if charge.discount_amount > 0:
        lines.append(f"🎟 Скидка по промокоду: <b>{format_rub(charge.discount_amount)}</b>")

    await callback.message.answer(
        "\n".join(lines) + f"\n\n<i>{PAYMENT_TERMS_NOTICE}</i>\n\nВыберите способ оплаты:",
        reply_markup=payment_method_keyboard(
            plan_id=plan.id,
            mode=mode,
            can_pay_with_balance=wallet_balance >= charge.final_amount,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("paywithbalance:"))
async def pay_plan_with_balance(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    current_user: User,
    bot,
) -> None:
    """Charge the selected tariff from the user's internal wallet balance."""
    if not callback.data or callback.message is None:
        await callback.answer()
        return

    _, plan_id, mode = callback.data.split(":")
    plan = await session.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return

    state_data = await state.get_data()
    promo = None
    promo_code = state_data.get("promocode_code")
    if promo_code:
        promo = await promocode_service.get_active(session, promo_code)

    try:
        activation_result = await payment_service.purchase_with_balance(
            session,
            user=current_user,
            plan=plan,
            promocode=promo,
            preferred_server_id=None,
            renewal=(mode == "renew"),
        )
    except RuntimeError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await state.clear()
    if activation_result.subscription is not None:
        await session.refresh(activation_result.subscription, attribute_names=["server", "plan"])
    await _send_payment_result(callback.message, bot, callback.message.chat.id, activation_result)
    await callback.answer("Подписка оплачена с баланса.")


@router.callback_query(F.data.startswith("paywithyookassa:"))
async def pay_plan_with_yookassa(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    current_user: User,
) -> None:
    """Create a hosted YooKassa payment after a payment method choice."""
    if not callback.data or callback.message is None:
        await callback.answer()
        return

    _, plan_id, mode = callback.data.split(":")
    plan = await session.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        await callback.answer("Тариф недоступен.", show_alert=True)
        return

    state_data = await state.get_data()
    promo = None
    promo_code = state_data.get("promocode_code")
    if promo_code:
        promo = await promocode_service.get_active(session, promo_code)

    payment = await payment_service.create_pending_payment(
        session,
        user=current_user,
        plan=plan,
        promocode=promo,
        preferred_server_id=None,
        renewal=(mode == "renew"),
    )

    provider = PaymentProvider(get_settings().payment_provider)
    if provider == PaymentProvider.YOOKASSA:
        if not yookassa_service.is_configured():
            await callback.message.answer("YooKassa ещё не настроена. Проверьте SHOP_ID, SECRET_KEY и RETURN_URL.")
            await callback.answer()
            return

        try:
            yookassa_payment = await yookassa_service.create_payment(
                payment=payment,
                description=f"Codex VPN - {plan.name}",
            )
        except httpx.HTTPError:
            await callback.message.answer(
                "Не удалось создать платёж в YooKassa. Проверьте настройки магазина и доступ к API."
            )
            await callback.answer()
            return

        payment.provider_payment_id = yookassa_payment.payment_id
        await session.flush()
        await callback.message.answer(
            (
                f"Тариф <b>{plan.name}</b>\n"
                f"Стоимость: <b>{format_rub(payment.amount_total)}</b>\n\n"
                f"<i>{PAYMENT_TERMS_NOTICE}</i>\n\n"
                "Откройте ссылку оплаты, а после оплаты нажмите «Проверить оплату»."
            ),
            reply_markup=payment_url_keyboard(yookassa_payment.confirmation_url, str(payment.id)),
        )
        await callback.answer("Ссылка на оплату готова.")
        return

    settings = get_settings()
    await callback.message.answer_invoice(
        title=f"VPN подписка - {plan.name}",
        description=plan.description,
        payload=payment.invoice_payload,
        provider_token=settings.telegram_provider_token,
        currency=payment.currency,
        prices=payment_service.build_prices(payment, plan),
    )
    await callback.answer("Счёт отправлен.")


@router.callback_query(F.data.startswith("paycheck:"))
async def check_yookassa_payment(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    current_user: User,
    bot,
) -> None:
    """Manually verify YooKassa payment status and apply its result."""
    if not callback.data or callback.message is None:
        await callback.answer()
        return

    payment_id = callback.data.split(":", maxsplit=1)[1]
    payment = await session.get(Payment, payment_id)
    if payment is None or payment.user_id != current_user.id:
        await callback.answer("Платёж не найден.", show_alert=True)
        return

    if payment.status == PaymentStatus.PAID:
        await callback.answer("Платёж уже подтверждён.")
        return

    if not payment.provider_payment_id:
        await callback.answer("У платежа нет ID YooKassa.", show_alert=True)
        return

    try:
        provider_payment = await yookassa_service.get_payment(payment.provider_payment_id)
    except httpx.HTTPError:
        await callback.answer("Не удалось проверить платёж. Попробуйте ещё раз.", show_alert=True)
        return

    if provider_payment.status != "succeeded":
        await callback.answer("Платёж ещё не подтверждён YooKassa.", show_alert=True)
        return

    activation_result = await payment_service.mark_paid_and_activate(
        session,
        payment=payment,
        provider_payment_id=payment.provider_payment_id,
        telegram_charge_id=None,
    )
    await state.clear()

    if activation_result.subscription is not None:
        await session.refresh(activation_result.subscription, attribute_names=["server", "plan"])
    await _send_payment_result(callback.message, bot, callback.message.chat.id, activation_result)
    await callback.answer("Платёж подтверждён.")
