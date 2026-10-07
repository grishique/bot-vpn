"""Telegram bot subclass that prepends the branding image to outbound messages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.methods import SendInvoice, SendMessage, SendPhoto, TelegramMethod
from aiogram.types import FSInputFile, Message


class BrandedBot(Bot):
    """Bot wrapper that sends the Codex VPN image before user-facing messages."""

    _branding_path = Path(__file__).resolve().parents[1] / "assets" / "content.png"

    async def _send_branding(self, chat_id: int | str) -> Message | None:
        """Send the branding image when it is available."""
        if not self._branding_path.exists():
            return None

        method = SendPhoto(chat_id=chat_id, photo=FSInputFile(self._branding_path))
        return await Bot.__call__(self, method)

    async def __call__(
        self,
        method: TelegramMethod[Any],
        request_timeout: int | None = None,
    ) -> Any:
        """Intercept outgoing Telegram methods and prepend the branding image."""
        if isinstance(method, (SendMessage, SendInvoice, SendPhoto)) and not getattr(
            method,
            "_skip_codex_branding",
            False,
        ):
            chat_id = getattr(method, "chat_id", None)
            if chat_id is not None:
                await self._send_branding(chat_id)
        return await Bot.__call__(self, method, request_timeout=request_timeout)
