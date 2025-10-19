from __future__ import annotations

from enum import StrEnum
from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.admin import AdminMenuCallback, ADMIN_ORDER_VIEW_PREFIX
from app.infrastructure.db.models import Order


class AdminPaymentsCallback(StrEnum):
    REFRESH = "admin:pay:refresh"
    VIEW_PENDING = "admin:pay:pending"
    VIEW_RECENT_PAID = "admin:pay:recent"
    SYNC_PENDING = "admin:pay:sync"
    SEARCH_ORDER = "admin:pay:search"


ADMIN_PAYMENTS_PENDING_PAGE_PREFIX = "admin:pay:pend:"
ADMIN_PAYMENTS_RECENT_PAGE_PREFIX = "admin:pay:rec:"


def payments_dashboard_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Refresh", callback_data=AdminPaymentsCallback.REFRESH.value)
    builder.button(text="Search order", callback_data=AdminPaymentsCallback.SEARCH_ORDER.value)
    builder.button(text="Pending invoices", callback_data=AdminPaymentsCallback.VIEW_PENDING.value)
    builder.button(text="Recent paid orders", callback_data=AdminPaymentsCallback.VIEW_RECENT_PAID.value)
    builder.button(text="Sync pending now", callback_data=AdminPaymentsCallback.SYNC_PENDING.value)
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def payments_orders_keyboard(
    orders: Sequence[Order],
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
    source_prefix: str,
    back_callback: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        status = order.status.value.replace("_", " ").title()
        amount = f"{order.total_amount} {order.currency}"
        product_name = getattr(order.product, "name", "-")
        if order.user is not None:
            user_display = order.user.display_name()
        else:
            user_display = f"id={order.user_id}"
        text = f"{status} • {amount} • {product_name[:18]} • {user_display}"
        builder.button(
            text=text,
            callback_data=f"{ADMIN_ORDER_VIEW_PREFIX}{order.public_id}",
        )
    nav_buttons: list[InlineKeyboardButton] = []
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"{source_prefix}{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text="Refresh",
            callback_data=f"{source_prefix}{page}",
        )
    )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️ Next",
                callback_data=f"{source_prefix}{page + 1}",
            )
        )
    builder.row(*nav_buttons)
    builder.button(text="Back", callback_data=back_callback)
    builder.adjust(1)
    return builder.as_markup()
