"""Service for storing audit events."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditService:
    """Small helper around audit log persistence."""

    async def log(
        self,
        session: AsyncSession,
        action: str,
        user_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Persist a new audit log entry."""
        entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
        session.add(entry)
        await session.flush()
        return entry


audit_service = AuditService()
