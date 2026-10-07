"""Payment creation and finalization logic."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from aiogram.types import LabeledPrice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.models.enums import PaymentProvider, PaymentPurpose, PaymentStatus
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.promocode import Promocode
from app.models.subscription import Subscription
from app.models.user import User
from app.services.audit_service import audit_service
from app.services.promocode_service import promocode_service
from app.services.referral_service import CodexPassReward, referral_service
from app.services.subscription_service import subscription_service
from app.utils.datetime import now_tz
from app.utils.security import generate_invoice_payload


@dataclass(slots=True)
class PaymentActivationResult:
    """Result payload returned after a successful payment."""

    subscription: Subscription | None
    codex_pass_reward: CodexPassReward | None
    balance_topup_amount: Decimal | None = None
    wallet_balance: Decimal | None = None


@dataclass(slots=True)
class PlanCharge:
    """Computed pricing details for a plan payment."""

    final_amount: Decimal
    discount_amount: Decimal
    promo_bonus_days: int


class PaymentService:
    """Create pending payments and finalize successful ones."""

    def get_plan_charge(self, plan: Plan, promocode: Promocode | None = None) -> PlanCharge:
        """Calculate the final amount and bonuses for a plan purchase."""
        discount = promocode_service.calculate_discount(plan, promocode)
        promo_bonus_days = promocode_service.get_bonus_days(promocode)
        final_amount = max(plan.price_amount - discount, Decimal("0.01"))
        return PlanCharge(
            final_amount=final_amount,
            discount_amount=discount,
            promo_bonus_days=promo_bonus_days,
        )

    async def create_pending_payment(
        self,
        session: AsyncSession,
        user: User,
        plan: Plan,
        promocode: Promocode | None = None,
        preferred_server_id: str | None = None,
        renewal: bool = False,
    ) -> Payment:
        """Create a pending payment record for a subscription purchase."""
        settings = get_settings()
        charge = self.get_plan_charge(plan, promocode)
        payment = Payment(
            user_id=user.id,
            plan_id=plan.id,
            promocode_id=promocode.id if promocode else None,
            provider=PaymentProvider(settings.payment_provider),
            purpose=PaymentPurpose.SUBSCRIPTION,
            status=PaymentStatus.PENDING,
            invoice_payload=generate_invoice_payload(),
            currency=settings.payment_currency,
            amount_minor=self.to_minor_units(charge.final_amount),
            amount_total=charge.final_amount,
            discount_amount=charge.discount_amount,
            metadata_json={
                "preferred_server_id": str(preferred_server_id) if preferred_server_id else None,
                "renewal": renewal,
                "plan_name": plan.name,
                "promo_bonus_days": charge.promo_bonus_days,
            },
        )
        session.add(payment)
        await session.flush()
        await audit_service.log(
            session,
            action="payment_created",
            user_id=str(user.id),
            entity_type="payment",
            entity_id=str(payment.id),
            details={
                "plan_id": str(plan.id),
                "amount": str(charge.final_amount),
                "purpose": payment.purpose.value,
            },
        )
        return payment

    async def create_balance_topup_payment(
        self,
        session: AsyncSession,
        user: User,
        amount: Decimal,
    ) -> Payment:
        """Create a pending payment record for a wallet top-up."""
        settings = get_settings()
        normalized_amount = max(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), Decimal("100.00"))
        payment = Payment(
            user_id=user.id,
            plan_id=None,
            promocode_id=None,
            provider=PaymentProvider(settings.payment_provider),
            purpose=PaymentPurpose.BALANCE_TOPUP,
            status=PaymentStatus.PENDING,
            invoice_payload=generate_invoice_payload(),
            currency=settings.payment_currency,
            amount_minor=self.to_minor_units(normalized_amount),
            amount_total=normalized_amount,
            discount_amount=Decimal("0.00"),
            metadata_json={
                "topup_amount": str(normalized_amount),
            },
        )
        session.add(payment)
        await session.flush()
        await audit_service.log(
            session,
            action="balance_topup_created",
            user_id=str(user.id),
            entity_type="payment",
            entity_id=str(payment.id),
            details={"amount": str(normalized_amount), "purpose": payment.purpose.value},
        )
        return payment

    async def get_by_payload(self, session: AsyncSession, payload: str) -> Payment | None:
        """Return a payment by its invoice payload."""
        result = await session.execute(
            select(Payment)
            .options(selectinload(Payment.plan), selectinload(Payment.user), selectinload(Payment.promocode))
            .where(Payment.invoice_payload == payload)
        )
        return result.scalar_one_or_none()

    async def get_by_provider_payment_id(
        self,
        session: AsyncSession,
        provider_payment_id: str,
    ) -> Payment | None:
        """Return a payment by its external provider id."""
        result = await session.execute(
            select(Payment)
            .options(selectinload(Payment.plan), selectinload(Payment.user), selectinload(Payment.promocode))
            .where(Payment.provider_payment_id == provider_payment_id)
        )
        return result.scalar_one_or_none()

    async def purchase_with_balance(
        self,
        session: AsyncSession,
        *,
        user: User,
        plan: Plan,
        promocode: Promocode | None = None,
        preferred_server_id: str | None = None,
        renewal: bool = False,
    ) -> PaymentActivationResult:
        """Charge the user's internal wallet balance and activate the subscription."""
        charge = self.get_plan_charge(plan, promocode)
        current_balance = Decimal(user.wallet_balance or Decimal("0.00"))
        if current_balance < charge.final_amount:
            raise RuntimeError("Недостаточно средств на балансе.")

        user.wallet_balance = current_balance - charge.final_amount
        payment = Payment(
            user_id=user.id,
            plan_id=plan.id,
            promocode_id=promocode.id if promocode else None,
            provider=PaymentProvider.BALANCE,
            purpose=PaymentPurpose.SUBSCRIPTION,
            status=PaymentStatus.PAID,
            invoice_payload=generate_invoice_payload(),
            currency=plan.currency,
            amount_minor=self.to_minor_units(charge.final_amount),
            amount_total=charge.final_amount,
            discount_amount=charge.discount_amount,
            metadata_json={
                "preferred_server_id": str(preferred_server_id) if preferred_server_id else None,
                "renewal": renewal,
                "plan_name": plan.name,
                "promo_bonus_days": charge.promo_bonus_days,
                "payment_method": "balance",
            },
            paid_at=now_tz(),
        )
        session.add(payment)
        await session.flush()

        subscription = await subscription_service.activate_from_payment(
            session,
            user=user,
            plan=plan,
            payment=payment,
            preferred_server_id=preferred_server_id,
            renewal=renewal,
        )
        await promocode_service.mark_used(session, promocode)
        codex_pass_reward = await referral_service.reward_if_eligible(session, user)
        await audit_service.log(
            session,
            action="balance_payment_paid",
            user_id=str(user.id),
            entity_type="payment",
            entity_id=str(payment.id),
            details={
                "subscription_id": str(subscription.id),
                "amount": str(payment.amount_total),
                "wallet_balance_left": str(user.wallet_balance),
            },
        )
        await session.flush()
        return PaymentActivationResult(subscription=subscription, codex_pass_reward=codex_pass_reward)

    async def mark_paid_and_activate(
        self,
        session: AsyncSession,
        payment: Payment,
        provider_payment_id: str,
        telegram_charge_id: str | None = None,
    ) -> PaymentActivationResult:
        """Mark a payment as paid and apply its business effect."""
        if payment.status == PaymentStatus.PAID:
            user = await session.get(User, payment.user_id)
            wallet_balance = Decimal(user.wallet_balance or Decimal("0.00")) if user is not None else None
            if payment.subscription_id is not None:
                await session.refresh(payment, attribute_names=["subscription"])
                return PaymentActivationResult(subscription=payment.subscription, codex_pass_reward=None)
            return PaymentActivationResult(
                subscription=None,
                codex_pass_reward=None,
                balance_topup_amount=payment.amount_total if payment.purpose == PaymentPurpose.BALANCE_TOPUP else None,
                wallet_balance=wallet_balance if payment.purpose == PaymentPurpose.BALANCE_TOPUP else None,
            )

        user = await session.get(User, payment.user_id)
        if user is None:
            raise RuntimeError("Payment refers to a missing user.")

        payment.status = PaymentStatus.PAID
        payment.provider_payment_id = provider_payment_id
        payment.telegram_charge_id = telegram_charge_id
        payment.paid_at = now_tz()

        if payment.purpose == PaymentPurpose.BALANCE_TOPUP:
            user.wallet_balance = Decimal(user.wallet_balance or Decimal("0.00")) + Decimal(payment.amount_total)
            await audit_service.log(
                session,
                action="balance_topped_up",
                user_id=str(user.id),
                entity_type="payment",
                entity_id=str(payment.id),
                details={
                    "amount": str(payment.amount_total),
                    "wallet_balance": str(user.wallet_balance),
                },
            )
            await session.flush()
            return PaymentActivationResult(
                subscription=None,
                codex_pass_reward=None,
                balance_topup_amount=payment.amount_total,
                wallet_balance=user.wallet_balance,
            )

        plan = await session.get(Plan, payment.plan_id) if payment.plan_id else None
        promo = await session.get(Promocode, payment.promocode_id) if payment.promocode_id else None
        if plan is None:
            raise RuntimeError("Subscription payment does not have a plan.")

        subscription = await subscription_service.activate_from_payment(
            session,
            user=user,
            plan=plan,
            payment=payment,
            preferred_server_id=payment.metadata_json.get("preferred_server_id"),
            renewal=bool(payment.metadata_json.get("renewal")),
        )
        await promocode_service.mark_used(session, promo)
        codex_pass_reward = await referral_service.reward_if_eligible(session, user)
        await audit_service.log(
            session,
            action="payment_paid",
            user_id=str(user.id),
            entity_type="payment",
            entity_id=str(payment.id),
            details={"subscription_id": str(subscription.id), "amount": str(payment.amount_total)},
        )
        await session.flush()
        return PaymentActivationResult(subscription=subscription, codex_pass_reward=codex_pass_reward)

    @staticmethod
    def to_minor_units(amount: Decimal) -> int:
        """Convert a decimal amount into Telegram minor units."""
        return int((amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def build_prices(self, payment: Payment, plan: Plan) -> list[LabeledPrice]:
        """Build Telegram invoice prices for the selected plan."""
        return [LabeledPrice(label=plan.name, amount=payment.amount_minor)]

    def build_topup_prices(self, payment: Payment) -> list[LabeledPrice]:
        """Build Telegram invoice prices for a balance top-up."""
        return [LabeledPrice(label="Пополнение баланса", amount=payment.amount_minor)]


payment_service = PaymentService()
