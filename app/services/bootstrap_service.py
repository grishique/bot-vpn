"""Startup bootstrap and seed data service."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models.enums import UserRole
from app.models.plan import Plan
from app.models.user import User


class BootstrapService:
    """Ensure required defaults exist in the database."""

    PLAN_BLUEPRINTS = (
        {
            "name": "Бесплатный тариф",
            "description": "Бесплатная подписка Codex VPN с лимитом 5 ГБ трафика.",
            "duration_days": 30,
            "price_amount": Decimal("0.00"),
            "currency": "RUB",
            "traffic_limit_gb": 5,
            "is_active": False,
            "sort_order": 5,
        },
        {
            "name": "1 мес стандарт",
            "description": "Стандартная подписка Codex VPN на 30 дней для 2 устройств.",
            "duration_days": 30,
            "price_amount": Decimal("100.00"),
            "currency": "RUB",
            "traffic_limit_gb": None,
            "is_active": True,
            "sort_order": 10,
        },
        {
            "name": "3 мес базовый",
            "description": "Базовая подписка Codex VPN на 90 дней для 2 устройств.",
            "duration_days": 90,
            "price_amount": Decimal("250.00"),
            "currency": "RUB",
            "traffic_limit_gb": None,
            "is_active": True,
            "sort_order": 20,
        },
        {
            "name": "12 мес оптимальный",
            "description": "Оптимальная подписка Codex VPN на 365 дней для 2 устройств.",
            "duration_days": 365,
            "price_amount": Decimal("750.00"),
            "currency": "RUB",
            "traffic_limit_gb": None,
            "is_active": True,
            "sort_order": 30,
        },
    )

    async def ensure_seed_data(self, session: AsyncSession) -> None:
        """Create or update the default plans."""
        result = await session.execute(select(Plan))
        existing_plans = result.scalars().all()
        plans_by_duration = {plan.duration_days: plan for plan in existing_plans if plan.price_amount > 0}
        free_plan = next((plan for plan in existing_plans if plan.name == "Бесплатный тариф"), None)

        for blueprint in self.PLAN_BLUEPRINTS:
            if blueprint["price_amount"] == 0:
                plan = free_plan
            else:
                plan = plans_by_duration.get(blueprint["duration_days"])

            if plan is None:
                session.add(Plan(**blueprint))
                continue

            plan.name = blueprint["name"]
            plan.description = blueprint["description"]
            plan.duration_days = blueprint["duration_days"]
            plan.price_amount = blueprint["price_amount"]
            plan.currency = blueprint["currency"]
            plan.traffic_limit_gb = blueprint["traffic_limit_gb"]
            plan.is_active = blueprint["is_active"]
            plan.sort_order = blueprint["sort_order"]

        await session.flush()

    async def sync_admin_roles(self, session: AsyncSession) -> None:
        """Apply administrator roles from the .env file."""
        settings = get_settings()
        if not settings.admin_ids:
            return

        result = await session.execute(select(User).where(User.telegram_id.in_(settings.admin_ids)))
        for user in result.scalars().all():
            user.role = UserRole.ADMIN
        await session.flush()


bootstrap_service = BootstrapService()
