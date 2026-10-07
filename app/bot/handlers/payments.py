"""Telegram payment handlers."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.services.notification_service import notification_service
from app.services.payment_service import payment_service
from app.utils.texts import format_balance_topup_success

router = Router(name="payments")


@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery, session: AsyncSession) -> None:
    """Validate a pre-checkout query before Telegram finalizes the payment."""
    payment = await payment_service.get_by_payload(session, query.invoice_payload)
    if payment is None:
        await query.answer(ok=False, error_message="Счёт не найден.")
        return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    bot,
) -> None:
    """Finalize a successful Telegram payment."""
    successful_payment = message.successful_payment
    if successful_payment is None:
        return

    payment = await payment_service.get_by_payload(session, successful_payment.invoice_payload)
    if payment is None:
        await message.answer("Платёж принят, но запись счёта не найдена. Обратитесь в поддержку.")
        return

    activation_result = await payment_service.mark_paid_and_activate(
        session,
        payment=payment,
        provider_payment_id=successful_payment.provider_payment_charge_id,
        telegram_charge_id=successful_payment.telegram_payment_charge_id,
    )
    await state.clear()

    if activation_result.balance_topup_amount is not None and activation_result.wallet_balance is not None:
        await message.answer(
            format_balance_topup_success(
                activation_result.balance_topup_amount,
                activation_result.wallet_balance,
            )
        )
        return

    settings = get_settings()
    await message.answer(settings.payment_success_text)

    if activation_result.codex_pass_reward is not None:
        await notification_service.send_codex_pass_reward(bot, activation_result.codex_pass_reward)

    if activation_result.subscription is None:
        return

    await session.refresh(activation_result.subscription, attribute_names=["server", "plan"])
    await notification_service.send_subscription_credentials(
        bot,
        message.chat.id,
        activation_result.subscription,
    )
