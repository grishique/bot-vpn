"""Helpers for timezone-aware date and time calculations."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config.settings import get_settings


def now_tz() -> datetime:
    """Return the current time in the configured timezone."""
    settings = get_settings()
    return datetime.now(tz=ZoneInfo(settings.timezone))
