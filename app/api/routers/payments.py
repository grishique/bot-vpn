"""Payment provider webhook endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.config.settings import get_settings
from app.database.session import AsyncSessionFactory
from app.models.enums import PaymentProvider, PaymentStatus
from app.services.notification_service import notification_service
from app.services.payment_service import payment_service
from app.services.yookassa_service import yookassa_service
from app.utils.texts import format_balance_topup_success

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/yookassa/webhook")
async def yookassa_webhook(request: Request) -> dict[str, bool]:
    """Handle YooKassa payment status notifications."""
    authorization_header = request.headers.get("Authorization")
    if not yookassa_service.is_valid_webhook(authorization_header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid YooKassa webhook secret")

    payload = await request.json()
    event = payload.get("event")
    payment_object = payload.get("object") or {}
    provider_payment_id = payment_object.get("id")

    if event != "payment.succeeded" or not provider_payment_id:
        return {"ok": True}

    # Treat the notification as a hint; retrieve trusted data from the provider.
    remote_payment = await yookassa_service.get_payment(provider_payment_id)
    if remote_payment.payment_id != provider_payment_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment id mismatch")

    async with AsyncSessionFactory() as session:
        payment = await payment_service.get_by_provider_payment_id(session, provider_payment_id)
        if payment is None:
            invoice_payload = remote_payment.invoice_payload
            if invoice_payload:
                payment = await payment_service.get_by_payload(session, invoice_payload)

        if payment is None:
            logger.warning("YooKassa webhook received for unknown payment %s", provider_payment_id)
            return {"ok": True}

        if payment.status == PaymentStatus.PAID:
            return {"ok": True}

        if payment.provider != PaymentProvider.YOOKASSA or not yookassa_service.matches_payment(remote_payment, payment):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment verification failed")

        activation_result = await payment_service.mark_paid_and_activate(
            session,
            payment=payment,
            provider_payment_id=provider_payment_id,
            telegram_charge_id=None,
        )
        await session.commit()

        bot = request.app.state.bot
        if activation_result.balance_topup_amount is not None and activation_result.wallet_balance is not None:
            await bot.send_message(
                payment.user.telegram_id,
                format_balance_topup_success(
                    activation_result.balance_topup_amount,
                    activation_result.wallet_balance,
                ),
            )
            return {"ok": True}

        if activation_result.codex_pass_reward is not None:
            await notification_service.send_codex_pass_reward(bot, activation_result.codex_pass_reward)

        if activation_result.subscription is not None:
            settings = get_settings()
            await session.refresh(activation_result.subscription, attribute_names=["server", "plan"])
            await bot.send_message(payment.user.telegram_id, settings.payment_success_text)
            await notification_service.send_subscription_credentials(
                bot,
                payment.user.telegram_id,
                activation_result.subscription,
            )

    return {"ok": True}
