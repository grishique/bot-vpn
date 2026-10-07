"""Referral program service and Codex Pass progression."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.referral import Referral
from app.models.subscription import Subscription
from app.models.user import User
from app.services.audit_service import audit_service
from app.services.subscription_service import subscription_service
from app.services.user_service import user_service
from app.utils.datetime import now_tz
from app.utils.texts import format_rub, render_progress_bar


@dataclass(frozen=True, slots=True)
class CodexPassLevel:
    """Single Codex Pass milestone."""

    level: int
    required_total_referrals: int
    reward_days: int = 0
    reward_balance_rub: Decimal = Decimal("0.00")

    @property
    def reward_months(self) -> int:
        """Return the reward length in whole months."""
        return self.reward_days // 30

    @property
    def reward_text(self) -> str:
        """Render a user-facing reward label."""
        if self.reward_balance_rub > 0:
            return f"{format_rub(self.reward_balance_rub)} на баланс"
        return f"+{self.reward_months} мес VPN"


@dataclass(slots=True)
class CodexPassStatus:
    """Current Codex Pass state shown in the UI."""

    display_level: int
    unlocked_level: int
    activated_referrals: int
    invites_to_next_reward: int
    next_reward_days: int | None
    next_reward_balance_rub: Decimal | None
    progress_percent: int
    progress_bar: str
    completed: bool

    @property
    def next_reward_months(self) -> int | None:
        """Return the next reward in months when available."""
        if self.next_reward_days is None:
            return None
        return self.next_reward_days // 30


@dataclass(slots=True)
class CodexPassReward:
    """Reward data emitted when a user unlocks a Codex Pass level."""

    referrer_telegram_id: int
    level: int
    reward_days: int
    reward_balance_rub: Decimal
    total_activated_referrals: int
    applied_to_active_subscription: bool
    new_expires_at: datetime | None
    wallet_balance: Decimal | None

    @property
    def reward_months(self) -> int:
        """Return the reward length in whole months."""
        return self.reward_days // 30


class ReferralService:
    """Service responsible for referral binding and Codex Pass rewards."""

    _levels = (
        CodexPassLevel(level=1, required_total_referrals=3, reward_balance_rub=Decimal("100.00")),
        CodexPassLevel(level=2, required_total_referrals=8, reward_days=60),
        CodexPassLevel(level=3, required_total_referrals=18, reward_days=90),
    )

    async def attach_by_code(
        self,
        session: AsyncSession,
        referee: User,
        referral_code: str,
    ) -> bool:
        """Attach a referee to a referrer if the relation is still free."""
        if not referral_code:
            return False

        existing = await session.execute(select(Referral).where(Referral.referee_id == referee.id))
        if existing.scalar_one_or_none() is not None:
            return False

        referrer = await user_service.get_by_referral_code(session, referral_code)
        if referrer is None or referrer.id == referee.id:
            return False

        referral = Referral(
            referrer_id=referrer.id,
            referee_id=referee.id,
            reward_days=0,
        )
        referee.referred_by_id = referrer.id
        session.add(referral)
        await session.flush()
        await audit_service.log(
            session,
            action="referral_attached",
            user_id=str(referee.id),
            entity_type="referral",
            entity_id=str(referral.id),
            details={
                "referrer_id": str(referrer.id),
                "referee_id": str(referee.id),
                "codex_pass_enabled": True,
            },
        )
        return True

    async def reward_if_eligible(self, session: AsyncSession, paying_user: User) -> CodexPassReward | None:
        """Count a converted referral and unlock Codex Pass rewards when needed."""
        result = await session.execute(select(Referral).where(Referral.referee_id == paying_user.id))
        referral = result.scalar_one_or_none()
        if referral is None or referral.reward_applied_at is not None:
            return None

        referrer = await session.get(User, referral.referrer_id)
        if referrer is None:
            return None

        referral.reward_applied_at = now_tz()
        activated_referrals = await self.count_activated_referrals(session, referrer.id)
        unlocked_levels = [
            level
            for level in self._levels
            if activated_referrals >= level.required_total_referrals and level.level > referrer.codex_pass_level
        ]

        await audit_service.log(
            session,
            action="referral_converted",
            user_id=str(referrer.id),
            entity_type="referral",
            entity_id=str(referral.id),
            details={
                "referee_id": str(paying_user.id),
                "activated_referrals": activated_referrals,
            },
        )

        if not unlocked_levels:
            await session.flush()
            return None

        reward_days = sum(level.reward_days for level in unlocked_levels)
        reward_balance_rub = sum((level.reward_balance_rub for level in unlocked_levels), Decimal("0.00"))
        target_level = unlocked_levels[-1].level
        referrer.codex_pass_level = target_level

        active_subscription = await subscription_service.get_active_for_user(session, referrer.id)
        applied_to_active_subscription = False
        new_expires_at: datetime | None = None
        if reward_days > 0:
            if active_subscription is not None and not subscription_service.is_free_plan(active_subscription.plan):
                await self._extend_active_subscription(session, active_subscription, reward_days)
                applied_to_active_subscription = True
                new_expires_at = active_subscription.expires_at
            else:
                referrer.bonus_days_balance += reward_days

        wallet_balance: Decimal | None = None
        if reward_balance_rub > 0:
            referrer.wallet_balance = Decimal(referrer.wallet_balance or Decimal("0.00")) + reward_balance_rub
            wallet_balance = Decimal(referrer.wallet_balance)

        await audit_service.log(
            session,
            action="codex_pass_reward_granted",
            user_id=str(referrer.id),
            entity_type="user",
            entity_id=str(referrer.id),
            details={
                "level": target_level,
                "reward_days": reward_days,
                "reward_balance_rub": str(reward_balance_rub),
                "activated_referrals": activated_referrals,
                "applied_to_active_subscription": applied_to_active_subscription,
            },
        )
        await session.flush()
        return CodexPassReward(
            referrer_telegram_id=referrer.telegram_id,
            level=target_level,
            reward_days=reward_days,
            reward_balance_rub=reward_balance_rub,
            total_activated_referrals=activated_referrals,
            applied_to_active_subscription=applied_to_active_subscription,
            new_expires_at=new_expires_at,
            wallet_balance=wallet_balance,
        )

    async def get_codex_pass_status(self, session: AsyncSession, user: User) -> CodexPassStatus:
        """Build the current Codex Pass progress card for a user."""
        activated_referrals = await self.count_activated_referrals(session, user.id)
        max_level = self._levels[-1].level
        if user.codex_pass_level >= max_level:
            return CodexPassStatus(
                display_level=max_level,
                unlocked_level=user.codex_pass_level,
                activated_referrals=activated_referrals,
                invites_to_next_reward=0,
                next_reward_days=None,
                next_reward_balance_rub=None,
                progress_percent=100,
                progress_bar=render_progress_bar(100),
                completed=True,
            )

        next_level = self._levels[user.codex_pass_level]
        previous_threshold = 0
        if user.codex_pass_level > 0:
            previous_threshold = self._levels[user.codex_pass_level - 1].required_total_referrals

        progress_current = max(activated_referrals - previous_threshold, 0)
        progress_total = next_level.required_total_referrals - previous_threshold
        progress_percent = int((progress_current / progress_total) * 100) if progress_total else 100
        invites_to_next_reward = max(next_level.required_total_referrals - activated_referrals, 0)

        return CodexPassStatus(
            display_level=min(user.codex_pass_level + 1, max_level),
            unlocked_level=user.codex_pass_level,
            activated_referrals=activated_referrals,
            invites_to_next_reward=invites_to_next_reward,
            next_reward_days=next_level.reward_days or None,
            next_reward_balance_rub=next_level.reward_balance_rub if next_level.reward_balance_rub > 0 else None,
            progress_percent=progress_percent,
            progress_bar=render_progress_bar(progress_percent),
            completed=False,
        )

    async def count_activated_referrals(self, session: AsyncSession, referrer_id: str) -> int:
        """Count referrals that have completed activation."""
        total = await session.scalar(
            select(func.count())
            .select_from(Referral)
            .where(
                Referral.referrer_id == referrer_id,
                Referral.reward_applied_at.is_not(None),
            )
        )
        return int(total or 0)

    async def _extend_active_subscription(
        self,
        session: AsyncSession,
        subscription: Subscription,
        reward_days: int,
    ) -> None:
        """Apply a Codex Pass reward to an active subscription immediately."""
        await subscription_service.extend_active_subscription(
            session,
            subscription,
            reward_days,
            audit_action=None,
        )


referral_service = ReferralService()
