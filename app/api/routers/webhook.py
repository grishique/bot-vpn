"""Telegram webhook endpoints."""

from __future__ import annotations

from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, status

from app.config.settings import get_settings

router = APIRouter(tags=["telegram"])


@router.post("")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    """Accept Telegram webhook updates and feed them into aiogram."""
    settings = get_settings()
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_header != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")

    bot = request.app.state.bot
    dispatcher = request.app.state.dispatcher

    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dispatcher.feed_webhook_update(bot, update)
    return {"ok": True}
