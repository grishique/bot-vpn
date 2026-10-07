"""VPN server model definition."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.subscription import Subscription


class VpnServer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configured VPN node backed by a 3x-ui panel."""

    __tablename__ = "vpn_servers"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    panel_url: Mapped[str] = mapped_column(String(255), nullable=False)
    panel_username: Mapped[str] = mapped_column(String(255), nullable=False)
    panel_password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    inbound_id: Mapped[int] = mapped_column(Integer, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    public_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sni: Mapped[str] = mapped_column(String(255), nullable=False)
    short_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), default="chrome", nullable=False)
    spider_x: Mapped[str] = mapped_column(String(255), default="/", nullable=False)
    flow: Mapped[str] = mapped_column(String(64), default="xtls-rprx-vision", nullable=False)
    transport: Mapped[str] = mapped_column(String(32), default="tcp", nullable=False)
    remark_prefix: Mapped[str] = mapped_column(String(64), default="vpn", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="server")
