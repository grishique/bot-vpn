"""3x-ui integration for managing VLESS Reality users."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from urllib.parse import quote, urlencode, urljoin

import httpx

from app.models.subscription import Subscription
from app.models.vpn_server import VpnServer
from app.services.server_service import server_service

logger = logging.getLogger(__name__)


class XUIError(RuntimeError):
    """Raised when 3x-ui API communication fails."""


class ThreeXUIService:
    """HTTP client for 3x-ui panels."""

    async def upsert_client(
        self,
        server: VpnServer,
        subscription: Subscription,
        expires_at: datetime,
        *,
        create_only: bool = False,
    ) -> str:
        """Create or update a VLESS client in the target inbound."""
        async with httpx.AsyncClient(base_url=server.panel_url, timeout=20.0, follow_redirects=True) as client:
            await self._login(client, server)
            payload = self._build_client_payload(server, subscription, expires_at)
            endpoint = self._get_client_endpoint(subscription, create_only=create_only)
            request_body = {
                "id": server.inbound_id,
                "settings": json.dumps({"clients": [payload]}, ensure_ascii=False),
            }
            response = await client.post(endpoint, json=request_body)
            data = self._ensure_success(response, endpoint)
            logger.info("3x-ui client synced: server=%s subscription=%s", server.name, subscription.id)
            return data.get("obj", "") if isinstance(data, dict) else ""

    async def delete_client(self, server: VpnServer, client_id: str | None) -> None:
        """Delete a VLESS client from the target inbound."""
        if not client_id:
            return

        async with httpx.AsyncClient(base_url=server.panel_url, timeout=20.0, follow_redirects=True) as client:
            await self._login(client, server)
            endpoint = f"panel/api/inbounds/{server.inbound_id}/delClient/{client_id}"
            response = await client.post(endpoint)
            self._ensure_success(response, endpoint)
            logger.info("3x-ui client deleted: server=%s client_id=%s", server.name, client_id)

    async def get_client_traffic(self, server: VpnServer, client_email: str) -> tuple[int, int] | None:
        """Return uploaded and downloaded bytes for a client."""
        async with httpx.AsyncClient(base_url=server.panel_url, timeout=20.0, follow_redirects=True) as client:
            await self._login(client, server)
            endpoint = f"panel/api/inbounds/getClientTraffics/{quote(client_email, safe='')}"
            response = await client.get(endpoint)
            data = self._ensure_success(response, endpoint)
            payload = data.get("obj")
            if not isinstance(payload, dict):
                return None
            upload = int(payload.get("up", 0) or 0)
            download = int(payload.get("down", 0) or 0)
            return upload, download

    def build_vless_url(self, server: VpnServer, subscription: Subscription) -> str:
        """Build a VLESS Reality connection link."""
        query = urlencode(
            {
                "encryption": "none",
                "flow": server.flow,
                "security": "reality",
                "sni": server.sni,
                "fp": server.fingerprint,
                "pbk": server.public_key,
                "sid": server.short_id,
                "spx": server.spider_x,
                "type": server.transport,
            },
            quote_via=quote,
            safe="/",
        )
        label = quote(self.build_server_subscription_title(server))
        return f"vless://{subscription.vless_uuid}@{server.host}:{server.port}?{query}#{label}"

    def build_server_subscription_title(self, server: VpnServer) -> str:
        """Build a subscription entry title for Happ/Hiddify."""
        return f"{self.build_server_display_name(server)}?VLESS | TCP | TLS"

    def build_server_display_name(self, server: VpnServer) -> str:
        """Normalize how the server is shown to the end user."""
        raw_name = server.name.strip()
        normalized = re.sub(r"^Codex\s*VPN\s*", "", raw_name, flags=re.IGNORECASE)
        normalized = re.sub(r"\s*-\d+\s*$", "", normalized).strip()
        if "Germany" in normalized and "Frankfurt" in normalized:
            return "🇩🇪 Германия(Frankfurt)"
        return normalized or raw_name

    async def _login(self, client: httpx.AsyncClient, server: VpnServer) -> None:
        """Authenticate against a 3x-ui panel."""
        response = await client.post(
            urljoin(server.panel_url, "login"),
            data={
                "username": server.panel_username,
                "password": server_service.get_panel_password(server),
            },
        )
        self._ensure_success(response, "login")

    def _build_client_payload(
        self,
        server: VpnServer,
        subscription: Subscription,
        expires_at: datetime,
    ) -> dict[str, object]:
        """Build the payload expected by x-ui style APIs."""
        expiry_ms = int(expires_at.timestamp() * 1000)
        traffic_limit_gb = int(subscription.plan.traffic_limit_gb or 0) if subscription.plan is not None else 0
        total_gb_bytes = traffic_limit_gb * 1024 * 1024 * 1024
        return {
            "id": subscription.vless_uuid,
            "flow": server.flow,
            "email": subscription.client_email,
            "limitIp": 2,
            "totalGB": total_gb_bytes,
            "expiryTime": expiry_ms,
            "enable": True,
            "subId": subscription.id.hex[:16],
            "tgId": "",
            "reset": 0,
        }

    def _get_client_endpoint(self, subscription: Subscription, *, create_only: bool) -> str:
        """Pick the proper panel endpoint for a client sync operation."""
        if create_only or not subscription.xui_client_id:
            return "panel/api/inbounds/addClient"
        return f"panel/api/inbounds/updateClient/{subscription.xui_client_id}"

    def _ensure_success(self, response: httpx.Response, endpoint: str) -> dict[str, object]:
        """Validate an HTTP response returned by the panel."""
        if response.status_code >= 400:
            raise XUIError(f"3x-ui request failed for {endpoint}: {response.status_code} {response.text}")

        data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise XUIError(f"3x-ui rejected request for {endpoint}: {data}")
        return data if isinstance(data, dict) else {}


xui_service = ThreeXUIService()
