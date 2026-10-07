"""Payment model definition."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.enums import PaymentProvider, PaymentPurpose, PaymentStatus
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.plan import Plan
    from app.models.promocode import Promocode
    from app.models.subscription import Subscription
    from app.models.user import User


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stored payment history item."""

    __tablename__ = "payments"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    subscription_id: Mapped[str | None] = mapped_column(
        ForeignKey("subscriptions.id"),
        nullable=True,
    )
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    promocode_id: Mapped[str | None] = mapped_column(ForeignKey("promocodes.id"), nullable=True)
    provider: Mapped[PaymentProvider] = mapped_column(
        SqlEnum(
            PaymentProvider,
            name="payment_provider",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=PaymentProvider.TELEGRAM,
        nullable=False,
    )
    purpose: Mapped[PaymentPurpose] = mapped_column(
        SqlEnum(
            PaymentPurpose,
            name="payment_purpose",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=PaymentPurpose.SUBSCRIPTION,
        nullable=False,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        SqlEnum(
            PaymentStatus,
            name="payment_status",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
        ),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    invoice_payload: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    amount_minor: Mapped[int] = mapped_column(nullable=False)
    amount_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="payments")
    subscription: Mapped["Subscription | None"] = relationship(back_populates="payments")
    plan: Mapped["Plan | None"] = relationship(back_populates="payments")
    promocode: Mapped["Promocode | None"] = relationship(back_populates="payments")
