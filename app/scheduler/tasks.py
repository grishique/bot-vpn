"""Celery tasks for subscription maintenance and broadcast."""

from __future__ import annotations

import asyncio
import logging

from aiogram.client.default import DefaultBotProperties
from sqlalchemy import select

from app.bot.branded_bot import BrandedBot
from app.bot.keyboards.inline import main_menu_keyboard
from app.config.settings import get_settings
from app.database.session import AsyncSessionFactory
from app.models.enums import PaymentProvider, PaymentStatus
from app.models.payment import Payment
from app.models.user import User
from app.scheduler.celery_app import celery_app
from app.services.notification_service import notification_service
from app.services.payment_service import payment_service
from app.services.subscription_service import subscription_service
from app.services.xui_service import XUIError, xui_service
from app.services.yookassa_service import yookassa_service

logger = logging.getLogger(__name__)


def _run(coro):
    """Run an async coroutine inside the current task."""
    return asyncio.run(coro)


async def _with_bot():
    """Build a fresh bot instance for worker tasks."""
    settings = get_settings()
    return BrandedBot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=settings.telegram_parse_mode),
    )


@celery_app.task(name="app.scheduler.tasks.send_expiration_reminders_task")
def send_expiration_reminders_task() -> None:
    """Send 3-day and 1-day expiration reminders."""
    _run(_send_expiration_reminders())


async def _send_expiration_reminders() -> None:
    settings = get_settings()
    bot = await _with_bot()
    try:
        async with AsyncSessionFactory() as session:
            for days_before in [settings.reminder_days_before_2, settings.reminder_days_before_1]:
                subscriptions = await subscription_service.get_due_reminders(session, days_before)
                for subscription in subscriptions:
                    await bot.send_message(
                        subscription.user.telegram_id,
                        "Напоминание о подписке.\n"
                        f"Тариф <b>{subscription.plan.name}</b> истекает через {days_before} дн.\n"
                        f"Дата окончания: <b>{subscription.expires_at:%d.%m.%Y %H:%M}</b>\n"
                        "Продлите подписку заранее, чтобы не потерять доступ.",
                    )
                    await subscription_service.mark_reminder_sent(session, subscription, days_before)
            await session.commit()
    finally:
        await bot.session.close()


@celery_app.task(name="app.scheduler.tasks.expire_subscriptions_task")
def expire_subscriptions_task() -> None:
    """Disable expired subscriptions and remove users from x-ui."""
    _run(_expire_subscriptions())


async def _expire_subscriptions() -> None:
    bot = await _with_bot()
    try:
        async with AsyncSessionFactory() as session:
            subscriptions = await subscription_service.get_expired(session)
            for subscription in subscriptions:
                await subscription_service.expire(session, subscription)
                await bot.send_message(
                    subscription.user.telegram_id,
                    "Срок вашей подписки закончился. Доступ к VPN отключён.\n"
                    "Оформите продление, чтобы снова получить доступ.",
                    reply_markup=main_menu_keyboard(),
                )
            await session.commit()
    finally:
        await bot.session.close()


@celery_app.task(name="app.scheduler.tasks.check_traffic_limits_task")
def check_traffic_limits_task() -> None:
    """Disable subscriptions that have exhausted their traffic quota."""
    _run(_check_traffic_limits())


async def _check_traffic_limits() -> None:
    bot = await _with_bot()
    try:
        async with AsyncSessionFactory() as session:
            subscriptions = await subscription_service.get_limited_active(session)
            for subscription in subscriptions:
                limit_gb = int(subscription.plan.traffic_limit_gb or 0)
                if limit_gb <= 0:
                    continue

                try:
                    traffic = await xui_service.get_client_traffic(subscription.server, subscription.client_email)
                except XUIError as exc:
                    logger.warning("Traffic sync failed for subscription %s: %s", subscription.id, exc)
                    continue

                if traffic is None:
                    continue

                upload, download = traffic
                used_bytes = upload + download
                limit_bytes = limit_gb * 1024 * 1024 * 1024
                if used_bytes < limit_bytes:
                    continue

                await subscription_service.deactivate_by_traffic_limit(session, subscription)
                await bot.send_message(
                    subscription.user.telegram_id,
                    "Бесплатная подписка израсходована.\n"
                    "Оплатите VPN с помощью баланса или купите подписку по кнопке «Купить подписку».",
                    reply_markup=main_menu_keyboard(),
                )

            await session.commit()
    finally:
        await bot.session.close()


@celery_app.task(name="app.scheduler.tasks.broadcast_message_task")
def broadcast_message_task(text: str) -> None:
    """Broadcast a message to all non-banned users."""
    _run(_broadcast_message(text))


async def _broadcast_message(text: str) -> None:
    bot = await _with_bot()
    sent = 0
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(select(User).where(User.is_banned.is_(False)))
            for user in result.scalars().all():
                try:
                    await bot.send_message(user.telegram_id, text)
                    sent += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Broadcast failed for user %s: %s", user.telegram_id, exc)
    finally:
        await bot.session.close()
    logger.info("Broadcast completed. sent=%s", sent)


@celery_app.task(name="app.scheduler.tasks.reconcile_yookassa_payments_task")
def reconcile_yookassa_payments_task() -> None:
    """Sync pending YooKassa payments in case a webhook was missed."""
    _run(_reconcile_yookassa_payments())


async def _reconcile_yookassa_payments() -> None:
    settings = get_settings()
    bot = await _with_bot()
    processed = 0
    try:
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(Payment)
                .where(
                    Payment.provider == PaymentProvider.YOOKASSA,
                    Payment.status == PaymentStatus.PENDING,
                    Payment.provider_payment_id.is_not(None),
                )
                .order_by(Payment.created_at.asc())
                .limit(50)
            )
            for payment in result.scalars().all():
                try:
                    provider_payment = await yookassa_service.get_payment(payment.provider_payment_id or "")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("YooKassa status sync failed for payment %s: %s", payment.id, exc)
                    continue

                if provider_payment.status != "succeeded":
                    continue

                activation_result = await payment_service.mark_paid_and_activate(
                    session,
                    payment=payment,
                    provider_payment_id=provider_payment.payment_id,
                    telegram_charge_id=None,
                )
                await session.commit()
                processed += 1

                user = await session.get(User, payment.user_id)
                if user is None:
                    logger.warning("Paid payment %s has no user during notification step", payment.id)
                    continue

                try:
                    await bot.send_message(user.telegram_id, settings.payment_success_text)
                    if activation_result.codex_pass_reward is not None:
                        await notification_service.send_codex_pass_reward(bot, activation_result.codex_pass_reward)
                    if activation_result.subscription is not None:
                        await session.refresh(activation_result.subscription, attribute_names=["server", "plan"])
                        await notification_service.send_subscription_credentials(
                            bot,
                            user.telegram_id,
                            activation_result.subscription,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Post-payment notification failed for payment %s: %s", payment.id, exc)

        if processed:
            logger.info("Reconciled YooKassa payments: %s", processed)
    finally:
        await bot.session.close()
