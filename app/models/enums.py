"""Application enum definitions."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Supported user roles."""

    USER = "user"
    ADMIN = "admin"


class SubscriptionStatus(StrEnum):
    """Supported subscription states."""

    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    """Supported payment states."""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentProvider(StrEnum):
    """Supported payment providers."""

    TELEGRAM = "telegram"
    YOOKASSA = "yookassa"
    BALANCE = "balance"


class PaymentPurpose(StrEnum):
    """Supported payment purposes."""

    SUBSCRIPTION = "subscription"
    BALANCE_TOPUP = "balance_topup"
