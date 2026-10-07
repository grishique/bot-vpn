"""User registration and lookup service."""

from __future__ import annotations

from aiogram.types import User as TelegramUser
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models.enums import UserRole
from app.models.user import User
from app.services.audit_service import audit_service
from app.utils.datetime import now_tz
from app.utils.security import generate_referral_code


class UserService:
    """Service that manages Telegram users."""

    async def get_by_telegram_id(self, session: AsyncSession, telegram_id: int) -> User | None:
        """Return a user by Telegram id."""
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_by_referral_code(self, session: AsyncSession, code: str) -> User | None:
        """Return a user by referral code."""
        result = await session.execute(select(User).where(User.referral_code == code.upper()))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        session: AsyncSession,
        tg_user: TelegramUser,
    ) -> User:
        """Create a user on first contact or refresh existing profile data."""
        user = await self.get_by_telegram_id(session, tg_user.id)
        settings = get_settings()
        is_admin = tg_user.id in settings.admin_ids

        if user is None:
            referral_code = await self._generate_unique_referral_code(session)
            user = User(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
                language_code=tg_user.language_code,
                referral_code=referral_code,
                role=UserRole.ADMIN if is_admin else UserRole.USER,
                last_seen_at=now_tz(),
            )
            session.add(user)
            await session.flush()
            await audit_service.log(
                session,
                action="user_created",
                user_id=str(user.id),
                entity_type="user",
                entity_id=str(user.id),
                details={"telegram_id": tg_user.id},
            )
            return user

        user.username = tg_user.username
        user.first_name = tg_user.first_name
        user.last_name = tg_user.last_name
        user.language_code = tg_user.language_code
        user.last_seen_at = now_tz()
        if is_admin and user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
        await session.flush()
        return user

    async def _generate_unique_referral_code(self, session: AsyncSession) -> str:
        """Generate a referral code that does not yet exist."""
        while True:
            code = generate_referral_code()
            exists = await session.execute(select(User.id).where(User.referral_code == code))
            if exists.scalar_one_or_none() is None:
                return code

    async def ban_user(self, session: AsyncSession, user: User) -> None:
        """Ban a user from interacting with the bot."""
        user.is_banned = True
        await audit_service.log(
            session,
            action="user_banned",
            user_id=str(user.id),
            entity_type="user",
            entity_id=str(user.id),
            details={"telegram_id": user.telegram_id},
        )
        await session.flush()

    async def unban_user(self, session: AsyncSession, user: User) -> None:
        """Restore access for a banned user."""
        user.is_banned = False
        await audit_service.log(
            session,
            action="user_unbanned",
            user_id=str(user.id),
            entity_type="user",
            entity_id=str(user.id),
            details={"telegram_id": user.telegram_id},
        )
        await session.flush()

    async def get_stats(self, session: AsyncSession) -> dict[str, int]:
        """Return coarse user statistics."""
        total_users = await session.scalar(select(func.count()).select_from(User))
        banned_users = await session.scalar(select(func.count()).select_from(User).where(User.is_banned.is_(True)))
        admin_users = await session.scalar(
            select(func.count()).select_from(User).where(User.role == UserRole.ADMIN)
        )
        return {
            "total_users": int(total_users or 0),
            "banned_users": int(banned_users or 0),
            "admin_users": int(admin_users or 0),
        }

    async def list_users(self, session: AsyncSession, limit: int = 20, offset: int = 0) -> list[User]:
        """Return users ordered by newest first."""
        result = await session.execute(
            select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all())


user_service = UserService()
