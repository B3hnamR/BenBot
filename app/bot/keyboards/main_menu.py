from __future__ import annotations

from enum import StrEnum

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class MainMenuCallback(StrEnum):
    HOME = "menu:home"
    PRODUCTS = "menu:products"
    CART = "menu:cart"
    ACCOUNT = "menu:account"
    SUPPORT = "menu:support"
    PROFILE = "menu:profile"
    ADMIN = "menu:admin"


def main_menu_keyboard(show_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Products", callback_data=MainMenuCallback.PRODUCTS.value)
    builder.button(text="View cart", callback_data=MainMenuCallback.CART.value)
    builder.button(text="My orders", callback_data=MainMenuCallback.ACCOUNT.value)
    builder.button(text="My profile", callback_data=MainMenuCallback.PROFILE.value)
    builder.button(text="Support", callback_data=MainMenuCallback.SUPPORT.value)
    if show_admin:
        builder.button(text="Admin panel", callback_data=MainMenuCallback.ADMIN.value)
    builder.adjust(1)
    return builder.as_markup()


def back_keyboard(callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Back", callback_data=callback)
    return builder.as_markup()
