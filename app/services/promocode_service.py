"""Promocode validation and pricing logic."""

from __future__ import annotations

from decimal import Decimal
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.plan import Plan
from app.models.promocode import Promocode
from app.utils.datetime import now_tz


class PromocodeService:
    """Validate and apply promocodes."""

    async def generate_unique_code(self, session: AsyncSession, prefix: str = "CODEX") -> str:
        """Generate a promocode string that does not yet exist."""
        while True:
            suffix = secrets.token_hex(3).upper()
            code = f"{prefix}-{suffix}"
            result = await session.execute(select(Promocode.id).where(Promocode.code == code))
            if result.scalar_one_or_none() is None:
                return code

    async def get_active(self, session: AsyncSession, code: str) -> Promocode | None:
        """Return an active promocode if it is still valid."""
        result = await session.execute(select(Promocode).where(Promocode.code == code.upper()))
        promo = result.scalar_one_or_none()
        if promo is None or not promo.is_active:
            return None
        if promo.max_usages is not None and promo.used_count >= promo.max_usages:
            return None
        if promo.expires_at is not None and promo.expires_at <= now_tz():
            return None
        return promo

    def calculate_discount(self, plan: Plan, promo: Promocode | None) -> Decimal:
        """Return the discount amount for the selected plan."""
        if promo is None:
            return Decimal("0.00")

        if promo.discount_amount is not None:
            return min(plan.price_amount, promo.discount_amount)

        if promo.discount_percent is not None:
            return (plan.price_amount * Decimal(promo.discount_percent) / Decimal("100")).quantize(
                Decimal("0.01")
            )

        return Decimal("0.00")

    def get_bonus_days(self, promo: Promocode | None) -> int:
        """Return extra subscription days granted by the promocode."""
        if promo is None:
            return 0
        return max(int(promo.bonus_days or 0), 0)

    async def mark_used(self, session: AsyncSession, promo: Promocode | None) -> None:
        """Increase usage counter when a promocode is redeemed."""
        if promo is None:
            return
        promo.used_count += 1
        await session.flush()


promocode_service = PromocodeService()
