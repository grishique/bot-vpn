"""Subscription lifecycle service."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import get_settings
from app.models.enums import SubscriptionStatus
from app.models.payment import Payment
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.vpn_server import VpnServer
from app.services.audit_service import audit_service
from app.services.server_service import server_service
from app.services.xui_service import xui_service
from app.utils.datetime import now_tz
from app.utils.security import generate_client_uuid, generate_subscription_token


class SubscriptionService:
    """Create, renew, switch and expire subscriptions."""

    PROMOCODE_PLAN_NAME = "Промокод"
    FREE_PLAN_NAME = "Бесплатный тариф"
    FREE_PLAN_TRAFFIC_LIMIT_GB = 5

    async def get_active_for_user(self, session: AsyncSession, user_id) -> Subscription | None:
        """Return the user's current active subscription."""
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.server), selectinload(Subscription.plan))
            .where(
                and_(
                    Subscription.user_id == user_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                )
            )
            .order_by(Subscription.expires_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def is_free_plan(self, plan: Plan | None) -> bool:
        """Return whether the plan is the one-time free tariff."""
        if plan is None:
            return False
        return (
            Decimal(plan.price_amount) == Decimal("0.00")
            and int(plan.traffic_limit_gb or 0) == self.FREE_PLAN_TRAFFIC_LIMIT_GB
        )

    async def get_or_create_free_plan(self, session: AsyncSession) -> Plan:
        """Return the hidden free plan used for first-time users."""
        result = await session.execute(select(Plan).where(Plan.name == self.FREE_PLAN_NAME).limit(1))
        plan = result.scalar_one_or_none()
        if plan is not None:
            return plan

        plan = Plan(
            name=self.FREE_PLAN_NAME,
            description="Бесплатная подписка Codex VPN с лимитом 5 ГБ трафика.",
            duration_days=30,
            price_amount=Decimal("0.00"),
            currency="RUB",
            traffic_limit_gb=self.FREE_PLAN_TRAFFIC_LIMIT_GB,
            is_active=False,
            sort_order=5,
        )
        session.add(plan)
        await session.flush()
        return plan

    async def activate_free_subscription(self, session: AsyncSession, user: User) -> Subscription:
        """Create the initial free subscription for a user exactly once."""
        if user.free_subscription_claimed:
            raise RuntimeError("Бесплатная подписка уже была выдана.")

        current = await self.get_active_for_user(session, user.id)
        if current is not None:
            return current

        server = await server_service.pick_server(session)
        if server is None:
            raise RuntimeError("Нет доступного VPN-сервера для выдачи подписки.")

        plan = await self.get_or_create_free_plan(session)
        now = now_tz()
        subscription = Subscription(
            user_id=user.id,
            server_id=server.id,
            plan_id=plan.id,
            plan=plan,
            xui_client_id=None,
            client_email=f"{server.remark_prefix}-{user.telegram_id}-{generate_client_uuid()[:8]}",
            vless_uuid=generate_client_uuid(),
            starts_at=now,
            expires_at=now + timedelta(days=plan.duration_days),
            status=SubscriptionStatus.ACTIVE,
            reminder_sent_1d=False,
            reminder_sent_3d=False,
        )
        session.add(subscription)
        await session.flush()

        subscription.access_url = xui_service.build_vless_url(server, subscription)
        await xui_service.upsert_client(
            server,
            subscription,
            subscription.expires_at,
            create_only=True,
        )
        subscription.xui_client_id = subscription.xui_client_id or subscription.vless_uuid
        user.free_subscription_claimed = True

        await audit_service.log(
            session,
            action="free_subscription_activated",
            user_id=str(user.id),
            entity_type="subscription",
            entity_id=str(subscription.id),
            details={
                "plan_id": str(plan.id),
                "server_id": str(server.id),
                "traffic_limit_gb": plan.traffic_limit_gb,
                "expires_at": subscription.expires_at.isoformat(),
            },
        )
        await session.flush()
        return subscription

    async def activate_from_payment(
        self,
        session: AsyncSession,
        user: User,
        plan: Plan,
        payment: Payment,
        preferred_server_id: str | None = None,
        renewal: bool = False,
    ) -> Subscription:
        """Create or extend a subscription after a paid invoice."""
        current = await self.get_active_for_user(session, user.id)
        server: VpnServer | None
        now = now_tz()
        bonus_days = user.bonus_days_balance
        promo_bonus_days = int(payment.metadata_json.get("promo_bonus_days", 0) or 0)
        total_days = plan.duration_days + bonus_days + promo_bonus_days
        replacing_free_plan = current is not None and self.is_free_plan(current.plan)

        if current is not None:
            server = current.server
            current.plan_id = plan.id
            current.plan = plan
            current.starts_at = now if replacing_free_plan else min(current.starts_at, now)
            if replacing_free_plan:
                current.expires_at = now + timedelta(days=total_days)
            else:
                current.expires_at = max(current.expires_at, now) + timedelta(days=total_days)
            current.status = SubscriptionStatus.ACTIVE
            current.reminder_sent_1d = False
            current.reminder_sent_3d = False
            subscription = current
        else:
            server = await server_service.pick_server(session, preferred_server_id)
            if server is None:
                raise RuntimeError("No active VPN servers configured.")

            subscription = Subscription(
                user_id=user.id,
                server_id=server.id,
                plan_id=plan.id,
                plan=plan,
                xui_client_id=None,
                client_email=f"{server.remark_prefix}-{user.telegram_id}-{generate_client_uuid()[:8]}",
                vless_uuid=generate_client_uuid(),
                starts_at=now,
                expires_at=now + timedelta(days=total_days),
                status=SubscriptionStatus.ACTIVE,
                reminder_sent_1d=False,
                reminder_sent_3d=False,
            )
            session.add(subscription)
            await session.flush()

        if server is None:
            raise RuntimeError("Subscription does not have an assigned server.")

        subscription.access_url = xui_service.build_vless_url(server, subscription)
        await xui_service.upsert_client(
            server,
            subscription,
            subscription.expires_at,
            create_only=current is None,
        )
        subscription.xui_client_id = subscription.xui_client_id or subscription.vless_uuid
        payment.subscription_id = subscription.id

        if bonus_days:
            user.bonus_days_balance = 0

        await audit_service.log(
            session,
            action="subscription_activated" if not renewal else "subscription_renewed",
            user_id=str(user.id),
            entity_type="subscription",
            entity_id=str(subscription.id),
            details={
                "plan_id": str(plan.id),
                "server_id": str(server.id),
                "expires_at": subscription.expires_at.isoformat(),
                "bonus_days_used": bonus_days,
                "promo_bonus_days": promo_bonus_days,
                "replaced_free_subscription": replacing_free_plan,
            },
        )
        await session.flush()
        return subscription

    async def get_or_create_promocode_plan(self, session: AsyncSession) -> Plan:
        """Return a hidden zero-cost plan for promocode-based activations."""
        result = await session.execute(select(Plan).where(Plan.name == self.PROMOCODE_PLAN_NAME).limit(1))
        plan = result.scalar_one_or_none()
        if plan is not None:
            return plan

        plan = Plan(
            name=self.PROMOCODE_PLAN_NAME,
            description="Доступ, выданный по промокоду.",
            duration_days=0,
            price_amount=Decimal("0.00"),
            currency="RUB",
            is_active=False,
            sort_order=1000,
        )
        session.add(plan)
        await session.flush()
        return plan

    async def activate_promocode_access(
        self,
        session: AsyncSession,
        user: User,
        extra_days: int,
        *,
        promocode_code: str,
    ) -> tuple[Subscription, bool]:
        """Grant or extend access immediately from a promocode."""
        current = await self.get_active_for_user(session, user.id)
        if current is not None:
            subscription = await self.extend_active_subscription(
                session,
                current,
                extra_days,
                audit_action="promocode_applied",
                audit_details={
                    "promocode_code": promocode_code,
                    "bonus_days": extra_days,
                    "activation_mode": "extend_active",
                },
            )
            return subscription, False

        server = await server_service.pick_server(session)
        if server is None:
            raise RuntimeError("No active VPN servers configured.")

        plan = await self.get_or_create_promocode_plan(session)
        now = now_tz()
        balance_days = max(int(user.bonus_days_balance or 0), 0)
        total_days = extra_days + balance_days

        subscription = Subscription(
            user_id=user.id,
            server_id=server.id,
            plan_id=plan.id,
            plan=plan,
            xui_client_id=None,
            client_email=f"{server.remark_prefix}-{user.telegram_id}-{generate_client_uuid()[:8]}",
            vless_uuid=generate_client_uuid(),
            starts_at=now,
            expires_at=now + timedelta(days=total_days),
            status=SubscriptionStatus.ACTIVE,
            reminder_sent_1d=False,
            reminder_sent_3d=False,
        )
        session.add(subscription)
        await session.flush()

        subscription.access_url = xui_service.build_vless_url(server, subscription)
        await xui_service.upsert_client(
            server,
            subscription,
            subscription.expires_at,
            create_only=True,
        )
        subscription.xui_client_id = subscription.xui_client_id or subscription.vless_uuid
        if balance_days:
            user.bonus_days_balance = 0

        await audit_service.log(
            session,
            action="promocode_subscription_activated",
            user_id=str(user.id),
            entity_type="subscription",
            entity_id=str(subscription.id),
            details={
                "plan_id": str(plan.id),
                "server_id": str(server.id),
                "promocode_code": promocode_code,
                "bonus_days": extra_days,
                "bonus_balance_days_used": balance_days,
                "expires_at": subscription.expires_at.isoformat(),
            },
        )
        await session.flush()
        return subscription, True

    async def extend_active_subscription(
        self,
        session: AsyncSession,
        subscription: Subscription,
        extra_days: int,
        *,
        audit_action: str | None = None,
        audit_details: dict[str, object] | None = None,
    ) -> Subscription:
        """Extend an active subscription immediately and sync the VPN panel."""
        if extra_days <= 0:
            return subscription

        await session.refresh(subscription, attribute_names=["server", "plan"])
        now = now_tz()
        subscription.expires_at = max(subscription.expires_at, now) + timedelta(days=extra_days)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.reminder_sent_1d = False
        subscription.reminder_sent_3d = False
        await xui_service.upsert_client(
            subscription.server,
            subscription,
            subscription.expires_at,
            create_only=False,
        )

        if audit_action:
            await audit_service.log(
                session,
                action=audit_action,
                user_id=str(subscription.user_id),
                entity_type="subscription",
                entity_id=str(subscription.id),
                details=audit_details or {},
            )

        await session.flush()
        return subscription

    async def switch_server(
        self,
        session: AsyncSession,
        subscription: Subscription,
        target_server: VpnServer,
    ) -> Subscription:
        """Move an active subscription to another configured server."""
        await session.refresh(subscription, attribute_names=["server"])
        old_server = subscription.server

        if old_server.id == target_server.id:
            return subscription

        await xui_service.upsert_client(
            target_server,
            subscription,
            subscription.expires_at,
            create_only=True,
        )
        subscription.xui_client_id = subscription.xui_client_id or subscription.vless_uuid
        await xui_service.delete_client(old_server, subscription.xui_client_id)
        subscription.server_id = target_server.id
        subscription.access_url = xui_service.build_vless_url(target_server, subscription)
        await audit_service.log(
            session,
            action="subscription_server_changed",
            user_id=str(subscription.user_id),
            entity_type="subscription",
            entity_id=str(subscription.id),
            details={"old_server_id": str(old_server.id), "new_server_id": str(target_server.id)},
        )
        await session.flush()
        return subscription

    async def get_due_reminders(self, session: AsyncSession, days_before: int) -> list[Subscription]:
        """Return active subscriptions that need a reminder."""
        flag_column = (
            Subscription.reminder_sent_1d if days_before == 1 else Subscription.reminder_sent_3d
        )
        start = now_tz() + timedelta(days=days_before)
        end = start + timedelta(days=1)

        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.user), selectinload(Subscription.server), selectinload(Subscription.plan))
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at >= start,
                Subscription.expires_at < end,
                flag_column.is_(False),
            )
        )
        return list(result.scalars().all())

    async def mark_reminder_sent(self, session: AsyncSession, subscription: Subscription, days_before: int) -> None:
        """Mark a reminder flag as delivered."""
        if days_before == 1:
            subscription.reminder_sent_1d = True
        else:
            subscription.reminder_sent_3d = True
        await session.flush()

    async def get_expired(self, session: AsyncSession) -> list[Subscription]:
        """Return subscriptions that have reached their end date."""
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.server), selectinload(Subscription.user), selectinload(Subscription.plan))
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.expires_at <= now_tz(),
            )
        )
        return list(result.scalars().all())

    async def get_limited_active(self, session: AsyncSession) -> list[Subscription]:
        """Return active subscriptions with a traffic limit."""
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.server), selectinload(Subscription.user), selectinload(Subscription.plan))
            .join(Subscription.plan)
            .where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Plan.traffic_limit_gb.is_not(None),
                Plan.traffic_limit_gb > 0,
            )
        )
        return list(result.scalars().all())

    async def expire(self, session: AsyncSession, subscription: Subscription) -> None:
        """Deactivate a subscription and remove it from the VPN server."""
        await session.refresh(subscription, attribute_names=["server"])
        await xui_service.delete_client(subscription.server, subscription.xui_client_id)
        subscription.status = SubscriptionStatus.EXPIRED
        await audit_service.log(
            session,
            action="subscription_expired",
            user_id=str(subscription.user_id),
            entity_type="subscription",
            entity_id=str(subscription.id),
            details={"server_id": str(subscription.server_id)},
        )
        await session.flush()

    async def deactivate_by_traffic_limit(self, session: AsyncSession, subscription: Subscription) -> None:
        """Disable a subscription whose traffic quota is fully consumed."""
        await session.refresh(subscription, attribute_names=["server", "plan"])
        await xui_service.delete_client(subscription.server, subscription.xui_client_id)
        subscription.status = SubscriptionStatus.CANCELLED
        await audit_service.log(
            session,
            action="subscription_traffic_limit_reached",
            user_id=str(subscription.user_id),
            entity_type="subscription",
            entity_id=str(subscription.id),
            details={
                "server_id": str(subscription.server_id),
                "plan_id": str(subscription.plan_id),
                "traffic_limit_gb": subscription.plan.traffic_limit_gb,
            },
        )
        await session.flush()

    def build_remote_profile_url(self, subscription: Subscription) -> str:
        """Build a remote subscription URL for Happ/Hiddify."""
        settings = get_settings()
        token = quote(generate_subscription_token(str(subscription.id)), safe="")
        return f"{settings.effective_public_base_url}{settings.api_prefix}/subscriptions/{token}"


subscription_service = SubscriptionService()
