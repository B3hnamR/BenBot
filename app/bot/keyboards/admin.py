from __future__ import annotations

from enum import StrEnum

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AdminMenuCallback(StrEnum):
    TOGGLE_SUBSCRIPTION = "admin:toggle_subscription"
    MANAGE_CHANNELS = "admin:manage_channels"
    MANAGE_PRODUCTS = "admin:manage_products"
    MANAGE_ORDERS = "admin:manage_orders"
    BACK_TO_MAIN = "admin:back_to_main"


def admin_menu_keyboard(subscription_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=("Disable subscription gate" if subscription_enabled else "Enable subscription gate"),
        callback_data=AdminMenuCallback.TOGGLE_SUBSCRIPTION.value,
    )
    builder.button(text="Required channels", callback_data=AdminMenuCallback.MANAGE_CHANNELS.value)
    builder.button(text="Products", callback_data=AdminMenuCallback.MANAGE_PRODUCTS.value)
    builder.button(text="Orders", callback_data=AdminMenuCallback.MANAGE_ORDERS.value)
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def admin_channels_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Add channel", callback_data="admin:channel:add")
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()
