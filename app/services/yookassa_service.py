"""YooKassa payment provider integration."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal
import secrets
from uuid import uuid4

import httpx

from app.config.settings import get_settings
from app.models.payment import Payment


@dataclass(slots=True)
class YooKassaPayment:
    """Normalized YooKassa payment payload used by the bot."""

    payment_id: str
    confirmation_url: str
    status: str
    amount: Decimal
    currency: str
    invoice_payload: str


class YooKassaService:
    """Create payments in YooKassa and validate incoming webhooks."""

    api_url = "https://api.yookassa.ru/v3/payments"

    def is_configured(self) -> bool:
        """Return True when all required YooKassa credentials are present."""
        settings = get_settings()
        return all(
            [
                settings.yookassa_shop_id,
                settings.yookassa_secret_key,
                settings.yookassa_return_url,
            ]
        )

    async def create_payment(self, payment: Payment, description: str) -> YooKassaPayment:
        """Create a hosted YooKassa payment and return its confirmation URL."""
        headers = self._build_headers()
        settings = get_settings()

        payload = {
            "amount": {
                "value": f"{Decimal(payment.amount_total):.2f}",
                "currency": payment.currency,
            },
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": settings.yookassa_return_url,
            },
            "description": description,
            "metadata": {
                "invoice_payload": payment.invoice_payload,
                "payment_id": str(payment.id),
                "plan_id": str(payment.plan_id) if payment.plan_id else "",
                "user_id": str(payment.user_id),
                "purpose": payment.purpose.value,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        confirmation = data.get("confirmation") or {}
        return YooKassaPayment(
            payment_id=data["id"],
            confirmation_url=confirmation.get("confirmation_url", ""),
            status=data["status"],
            amount=Decimal(data["amount"]["value"]),
            currency=data["amount"]["currency"],
            invoice_payload=(data.get("metadata") or {}).get("invoice_payload", ""),
        )

    async def get_payment(self, provider_payment_id: str) -> YooKassaPayment:
        """Fetch the current payment status from YooKassa."""
        headers = self._build_headers(with_idempotence=False)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.api_url}/{provider_payment_id}", headers=headers)
            response.raise_for_status()
            data = response.json()

        confirmation = data.get("confirmation") or {}
        return YooKassaPayment(
            payment_id=data["id"],
            confirmation_url=confirmation.get("confirmation_url", ""),
            status=data["status"],
            amount=Decimal(data["amount"]["value"]),
            currency=data["amount"]["currency"],
            invoice_payload=(data.get("metadata") or {}).get("invoice_payload", ""),
        )

    def is_valid_webhook(self, authorization_header: str | None) -> bool:
        """Validate a webhook secret when one is configured."""
        settings = get_settings()
        if not settings.yookassa_webhook_secret:
            return True
        return secrets.compare_digest(authorization_header or "", settings.yookassa_webhook_secret)

    @staticmethod
    def matches_payment(remote: YooKassaPayment, payment: Payment) -> bool:
        """Match a confirmed provider payment to the expected local invoice."""
        return (
            remote.status == "succeeded"
            and remote.amount == Decimal(payment.amount_total)
            and remote.currency == payment.currency
            and remote.invoice_payload == payment.invoice_payload
            and (not payment.provider_payment_id or remote.payment_id == payment.provider_payment_id)
        )

    def _build_headers(self, *, with_idempotence: bool = True) -> dict[str, str]:
        """Build authenticated request headers for YooKassa."""
        settings = get_settings()
        auth_value = base64.b64encode(
            f"{settings.yookassa_shop_id}:{settings.yookassa_secret_key}".encode("utf-8")
        ).decode("utf-8")
        headers = {
            "Authorization": f"Basic {auth_value}",
            "Content-Type": "application/json",
        }
        if with_idempotence:
            headers["Idempotence-Key"] = str(uuid4())
        return headers


yookassa_service = YooKassaService()
