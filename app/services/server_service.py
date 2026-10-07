"""VPN server management service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.models.vpn_server import VpnServer
from app.services.audit_service import audit_service
from app.utils.security import decrypt_text, encrypt_text


class ServerService:
    """Manage VPN server records and selection."""

    async def list_active(self, session: AsyncSession) -> list[VpnServer]:
        """Return active servers ordered by priority."""
        result = await session.execute(
            select(VpnServer).where(VpnServer.is_active.is_(True)).order_by(VpnServer.sort_order, VpnServer.name)
        )
        return list(result.scalars().all())

    async def get_by_id(self, session: AsyncSession, server_id: str) -> VpnServer | None:
        """Load a server by its id."""
        return await session.get(VpnServer, server_id)

    async def pick_server(self, session: AsyncSession, preferred_server_id: str | None = None) -> VpnServer | None:
        """Pick the best server for a new subscription."""
        if preferred_server_id:
            server = await self.get_by_id(session, preferred_server_id)
            if server is not None and server.is_active:
                return server

        settings = get_settings()
        if settings.default_server_id:
            server = await self.get_by_id(session, settings.default_server_id)
            if server is not None and server.is_active:
                return server

        servers = await self.list_active(session)
        return servers[0] if servers else None

    async def add_server(
        self,
        session: AsyncSession,
        name: str,
        panel_url: str,
        panel_username: str,
        panel_password: str,
        inbound_id: int,
        host: str,
        port: int,
        public_key: str,
        sni: str,
        short_id: str,
        fingerprint: str = "chrome",
        spider_x: str = "/",
        flow: str = "xtls-rprx-vision",
        transport: str = "tcp",
        remark_prefix: str = "vpn",
        sort_order: int = 100,
    ) -> VpnServer:
        """Persist a new VPN server entry."""
        server = VpnServer(
            name=name,
            panel_url=panel_url.rstrip("/") + "/",
            panel_username=panel_username,
            panel_password_encrypted=encrypt_text(panel_password),
            inbound_id=inbound_id,
            host=host,
            port=port,
            public_key=public_key,
            sni=sni,
            short_id=short_id,
            fingerprint=fingerprint,
            spider_x=spider_x,
            flow=flow,
            transport=transport,
            remark_prefix=remark_prefix,
            sort_order=sort_order,
            is_active=True,
        )
        session.add(server)
        await session.flush()
        await audit_service.log(
            session,
            action="server_added",
            entity_type="vpn_server",
            entity_id=str(server.id),
            details={"name": name, "host": host, "port": port, "inbound_id": inbound_id},
        )
        return server

    async def remove_server(self, session: AsyncSession, server: VpnServer) -> None:
        """Delete a server entry from the database."""
        await audit_service.log(
            session,
            action="server_removed",
            entity_type="vpn_server",
            entity_id=str(server.id),
            details={"name": server.name},
        )
        await session.delete(server)

    def get_panel_password(self, server: VpnServer) -> str:
        """Decrypt a stored panel password."""
        return decrypt_text(server.panel_password_encrypted)


server_service = ServerService()
