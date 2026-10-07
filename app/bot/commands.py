"""Telegram bot command registration."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from app.config.settings import get_settings


async def _delete_scope_commands(bot: Bot, scope: object, language_code: str | None = None) -> None:
    """Delete commands for a scope, ignoring missing-command responses."""
    try:
        await bot.delete_my_commands(scope=scope, language_code=language_code)
    except Exception:
        # Telegram may return an error when a scope has no explicit commands yet.
        # That case is harmless for our cleanup pass.
        pass


async def setup_commands(bot: Bot) -> None:
    """Register user and administrator bot commands."""
    settings = get_settings()

    user_commands = [
        BotCommand(command="start", description="Запуск и главное меню"),
        BotCommand(command="menu", description="Показать меню"),
    ]
    admin_commands = [
        *user_commands,
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="users", description="Пользователи"),
        BotCommand(command="user", description="Карточка пользователя"),
        BotCommand(command="broadcast", description="Рассылка"),
        BotCommand(command="addserver", description="Добавить сервер"),
        BotCommand(command="removeserver", description="Удалить сервер"),
        BotCommand(command="createpromocode", description="Создать промокод"),
        BotCommand(command="promocodes", description="Промокоды"),
        BotCommand(command="ban", description="Заблокировать пользователя"),
        BotCommand(command="unban", description="Разблокировать пользователя"),
        BotCommand(command="restart", description="Перезапуск"),
    ]

    scopes_to_clear = [
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ]
    for admin_id in settings.admin_ids:
        scopes_to_clear.append(BotCommandScopeChat(chat_id=admin_id))

    for scope in scopes_to_clear:
        await _delete_scope_commands(bot, scope)
        await _delete_scope_commands(bot, scope, language_code="ru")

    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault(), language_code="ru")
    await bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands(user_commands, scope=BotCommandScopeAllPrivateChats(), language_code="ru")

    for admin_id in settings.admin_ids:
        admin_scope = BotCommandScopeChat(chat_id=admin_id)
        await bot.set_my_commands(admin_commands, scope=admin_scope)
        await bot.set_my_commands(admin_commands, scope=admin_scope, language_code="ru")
