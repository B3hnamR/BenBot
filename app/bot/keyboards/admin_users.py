from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.admin import AdminMenuCallback, ADMIN_ORDER_VIEW_PREFIX
from app.infrastructure.db.models import Order, UserProfile

ADMIN_USER_VIEW_PREFIX = "admin:user:view:"
ADMIN_USER_TOGGLE_BLOCK_PREFIX = "admin:user:toggle:"
ADMIN_USER_EDIT_NOTES_PREFIX = "admin:user:notes:"
ADMIN_USER_VIEW_ORDERS_PREFIX = "admin:user:orders:"
ADMIN_USER_BACK = "admin:user:back"
ADMIN_USER_SEARCH = "admin:user:search"
ADMIN_USER_SEARCH = "admin:user:search"


def users_overview_keyboard(users: Sequence[UserProfile]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in users:
        label = user.display_name()
        builder.button(
            text=label,
            callback_data=f"{ADMIN_USER_VIEW_PREFIX}{user.id}",
        )
    builder.button(text="Search user", callback_data=ADMIN_USER_SEARCH)
    builder.button(text="Search user", callback_data=ADMIN_USER_SEARCH)
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def user_detail_keyboard(user: UserProfile) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Block user" if not user.is_blocked else "Unblock user",
        callback_data=f"{ADMIN_USER_TOGGLE_BLOCK_PREFIX}{user.id}",
    )
    builder.button(
        text="Edit notes",
        callback_data=f"{ADMIN_USER_EDIT_NOTES_PREFIX}{user.id}",
    )
    builder.button(
        text="View orders",
        callback_data=f"{ADMIN_USER_VIEW_ORDERS_PREFIX}{user.id}",
    )
    builder.button(text="Back", callback_data=ADMIN_USER_BACK)
    builder.adjust(1)
    return builder.as_markup()


def user_orders_keyboard(user_id: int, orders: Sequence[Order]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        status = order.status.value.replace("_", " ").title()
        builder.button(
            text=f"{status} - {order.total_amount} {order.currency}",
            callback_data=f"{ADMIN_ORDER_VIEW_PREFIX}{order.public_id}",
        )
    builder.button(text="Back", callback_data=f"{ADMIN_USER_VIEW_PREFIX}{user_id}")
    builder.button(text="Back to users", callback_data=ADMIN_USER_BACK)
    builder.adjust(1)
    return builder.as_markup()


