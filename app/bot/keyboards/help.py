from __future__ import annotations

from enum import StrEnum

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class HelpCallback(StrEnum):
    MAIN_MENU = "help:main"
    CATEGORY = "help:cat"
    ITEM = "help:item"
    BACK_TO_MENU = "help:menu"


def help_categories_keyboard(categories: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for cat_id, title in categories:
        builder.button(text=title, callback_data=f"{HelpCallback.CATEGORY.value}:{cat_id}")
    builder.button(text="Back to menu", callback_data=HelpCallback.BACK_TO_MENU.value)
    builder.adjust(1)
    return builder.as_markup()


def help_items_keyboard(cat_id: str, items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item_id, title in items:
        builder.button(text=title, callback_data=f"{HelpCallback.ITEM.value}:{cat_id}:{item_id}")
    builder.button(text="Back", callback_data=HelpCallback.MAIN_MENU.value)
    builder.adjust(1)
    return builder.as_markup()
