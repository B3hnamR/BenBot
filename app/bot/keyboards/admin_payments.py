from __future__ import annotations

from enum import StrEnum
from typing import Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.admin import AdminMenuCallback, ADMIN_ORDER_VIEW_PREFIX
from app.infrastructure.db.models import Order


class AdminPaymentsCallback(StrEnum):
    REFRESH = "admin:pay:refresh"
    VIEW_PENDING = "admin:pay:pending"
    VIEW_RECENT_PAID = "admin:pay:recent"
    SYNC_PENDING = "admin:pay:sync"


def payments_dashboard_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Refresh", callback_data=AdminPaymentsCallback.REFRESH.value)
    builder.button(text="Pending invoices", callback_data=AdminPaymentsCallback.VIEW_PENDING.value)
    builder.button(text="Recent paid orders", callback_data=AdminPaymentsCallback.VIEW_RECENT_PAID.value)
    builder.button(text="Sync pending now", callback_data=AdminPaymentsCallback.SYNC_PENDING.value)
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def payments_orders_keyboard(orders: Sequence[Order], back_callback: AdminPaymentsCallback) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        status = order.status.value.replace("_", " ").title()
        amount = f"{order.total_amount} {order.currency}"
        builder.button(
            text=f"{status} • {amount}",
            callback_data=f"{ADMIN_ORDER_VIEW_PREFIX}{order.public_id}",
        )
    builder.button(text="Back", callback_data=back_callback.value)
    builder.adjust(1)
    return builder.as_markup()
