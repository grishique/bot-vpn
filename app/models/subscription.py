"""Subscription model definition."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import SubscriptionStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.payment import Payment
    from app.models.plan import Plan
    from app.models.user import User
    from app.models.vpn_server import VpnServer


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """User subscription bound to a VPN server and a plan."""

    __tablename__ = "subscriptions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    server_id: Mapped[str] = mapped_column(ForeignKey("vpn_servers.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), nullable=False)
    xui_client_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    client_email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    vless_uuid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    access_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SubscriptionStatus] = mapped_column(
        SqlEnum(
            SubscriptionStatus,
            name="subscription_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=SubscriptionStatus.PENDING,
        nullable=False,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reminder_sent_3d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reminder_sent_1d: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped["User"] = relationship(back_populates="subscriptions")
    server: Mapped["VpnServer"] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship(back_populates="subscriptions")
    payments: Mapped[list["Payment"]] = relationship(back_populates="subscription")
