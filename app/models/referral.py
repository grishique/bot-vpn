"""Referral model definition."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class Referral(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Referral relation between a referrer and a new user."""

    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("referee_id", name="uq_referral_referee"),)

    referrer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    referee_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reward_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    referrer: Mapped["User"] = relationship(
        back_populates="referrals_as_referrer",
        foreign_keys=[referrer_id],
    )
    referee: Mapped["User"] = relationship(
        back_populates="referrals_as_referee",
        foreign_keys=[referee_id],
    )
