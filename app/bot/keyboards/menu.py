"""Reply keyboards for the main menu."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.utils.texts import (
    MENU_ACCOUNT,
    MENU_BUY,
    MENU_CODEX_PASS,
    MENU_PROMOCODE,
    MENU_PROMOCODE_CANCEL,
    MENU_RENEW,
    MENU_SUPPORT,
    MENU_USAGE_TERMS,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Build the main user menu."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_BUY), KeyboardButton(text=MENU_RENEW)],
            [KeyboardButton(text=MENU_ACCOUNT), KeyboardButton(text=MENU_PROMOCODE)],
            [KeyboardButton(text=MENU_CODEX_PASS), KeyboardButton(text=MENU_USAGE_TERMS)],
            [KeyboardButton(text=MENU_SUPPORT)],
        ],
        resize_keyboard=True,
    )


def promocode_input_keyboard() -> ReplyKeyboardMarkup:
    """Build a temporary keyboard for promocode entry mode."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MENU_PROMOCODE_CANCEL)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
