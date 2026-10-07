"""Public subscription export endpoints for VPN clients."""

from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.session import AsyncSessionFactory
from app.models.enums import SubscriptionStatus
from app.models.subscription import Subscription
from app.services.xui_service import XUIError, xui_service
from app.utils.security import parse_subscription_token

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _as_base64_header(value: str) -> str:
    """Encode a UTF-8 value into the ASCII-safe format supported by client apps."""
    return f"base64:{base64.b64encode(value.encode('utf-8')).decode('ascii')}"


def _format_gb(value_bytes: int) -> str:
    """Render bytes as a compact GB value."""
    gb_value = value_bytes / (1024 * 1024 * 1024)
    if gb_value.is_integer():
        return f"{int(gb_value)} ГБ"
    return f"{gb_value:.1f} ГБ"


@router.get("/{token}")
async def export_subscription(token: str) -> Response:
    """Return a standard subscription payload for Happ/Hiddify."""
    try:
        subscription_id = parse_subscription_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found.") from exc

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(Subscription)
            .options(selectinload(Subscription.server), selectinload(Subscription.plan))
            .where(Subscription.id == subscription_id)
        )
        subscription = result.scalar_one_or_none()

    if subscription is None or subscription.status != SubscriptionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found.")

    expire_timestamp = int(subscription.expires_at.timestamp())
    support_url = "https://t.me/CodexPrivacybot"
    profile_title = "CodexVPN | Подписка"
    access_url = xui_service.build_vless_url(subscription.server, subscription)

    upload = 0
    download = 0
    try:
        traffic = await xui_service.get_client_traffic(subscription.server, subscription.client_email)
    except XUIError:
        traffic = None
    if traffic is not None:
        upload, download = traffic

    total = 0
    if subscription.plan.traffic_limit_gb:
        total = int(subscription.plan.traffic_limit_gb) * 1024 * 1024 * 1024

    traffic_line = "↕️ Трафик: Безлимит"
    if total > 0:
        traffic_line = f"↕️ Трафик: {_format_gb(upload + download)}/{_format_gb(total)}"
    tariff_name = "Бесплатный" if subscription.plan.price_amount == 0 else subscription.plan.name
    announcement = (
        f"ℹ️ Ваш тариф: {tariff_name}\n"
        f"{traffic_line}\n"
        "Покупка в боте @CodexPrivacybot"
    )

    userinfo = f"upload={upload}; download={download}; total={total}; expire={expire_timestamp}"
    body = "\n".join(
        [
            f"#profile-title: {_as_base64_header(profile_title)}",
            "#profile-update-interval: 24",
            f"#subscription-userinfo: {userinfo}",
            f"#support-url: {support_url}",
            f"#announce: {_as_base64_header(announcement)}",
            "#subscriptions-collapse: 0",
            "#subscriptions-expand-now: 1",
            "#ping-result: icon",
            f"#profile-web-page-url: {support_url}",
            access_url,
        ]
    )
    headers = {
        "Content-Disposition": 'attachment; filename="codexvpn-subscription.txt"',
        "Profile-Title": _as_base64_header(profile_title),
        "profile-update-interval": "24",
        "subscription-userinfo": userinfo,
        "support-url": support_url,
        "announce": _as_base64_header(announcement),
        "subscriptions-collapse": "0",
        "subscriptions-expand-now": "1",
        "ping-result": "icon",
        "profile-web-page-url": support_url,
    }
    return Response(content=body, media_type="text/plain; charset=utf-8", headers=headers)
