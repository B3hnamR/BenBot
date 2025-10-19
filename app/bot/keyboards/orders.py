from __future__ import annotations

from typing import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.main_menu import MainMenuCallback
from app.infrastructure.db.models import Order
from app.core.enums import OrderStatus
from app.services.crypto_payment_service import OXAPAY_EXTRA_KEY
from app.bot.keyboards.support import SUPPORT_ORDER_CREATE_PREFIX


ORDER_CONFIRM_CALLBACK = "order:confirm"
ORDER_CANCEL_CALLBACK = "order:cancel"
ORDER_VIEW_PREFIX = "order:view:"
ORDER_LIST_BACK_CALLBACK = "order:list_back"
ORDER_LIST_PAGE_PREFIX = "order:list_page:"
ORDER_CANCEL_ORDER_PREFIX = "order:cancel_order:"
ORDER_REISSUE_PREFIX = "order:reissue:"


def order_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Confirm order", callback_data=ORDER_CONFIRM_CALLBACK)
    builder.button(text="Cancel", callback_data=ORDER_CANCEL_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


def orders_list_keyboard(
    orders: Iterable[Order],
    *,
    page: int,
    page_size: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        builder.button(
            text=_order_summary_line(order),
            callback_data=f"{ORDER_VIEW_PREFIX}{order.public_id}",
        )
    nav_buttons: list[InlineKeyboardButton] = []
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"{ORDER_LIST_PAGE_PREFIX}{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text="Refresh",
            callback_data=f"{ORDER_LIST_PAGE_PREFIX}{page}",
        )
    )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️ Next",
                callback_data=f"{ORDER_LIST_PAGE_PREFIX}{page + 1}",
            )
        )
    builder.row(*nav_buttons)
    builder.button(text="Back to menu", callback_data=MainMenuCallback.PRODUCTS.value)
    builder.adjust(1)
    return builder.as_markup()


def order_details_keyboard(
    order: Order,
    pay_link: str | None = None,
    *,
    page: int | None = None,
    include_support_button: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if pay_link and order.status == OrderStatus.AWAITING_PAYMENT:
        builder.button(text="Open crypto checkout", url=pay_link)
    builder.button(
        text="Refresh status",
        callback_data=f"{ORDER_VIEW_PREFIX}{order.public_id}",
    )
    if order.status == OrderStatus.AWAITING_PAYMENT:
        builder.button(
            text="Cancel order",
            callback_data=f"{ORDER_CANCEL_ORDER_PREFIX}{order.public_id}",
        )
    if order.status in {OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
        builder.button(
            text="Create new invoice",
            callback_data=f"{ORDER_REISSUE_PREFIX}{order.public_id}",
        )
    if include_support_button:
        builder.button(
            text="Need help with this order",
            callback_data=f"{SUPPORT_ORDER_CREATE_PREFIX}{order.public_id}",
        )
    back_callback = (
        f"{ORDER_LIST_PAGE_PREFIX}{max(page or 0, 0)}"
        if page is not None
        else ORDER_LIST_BACK_CALLBACK
    )
    builder.button(text="Back to orders", callback_data=back_callback)
    builder.button(text="Back to menu", callback_data=MainMenuCallback.PRODUCTS.value)
    builder.adjust(1)
    return builder.as_markup()


def order_cancel_keyboard(callback_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Cancel", callback_data=callback_data)
    builder.adjust(1)
    return builder.as_markup()


def _order_summary_line(order: Order) -> str:
    status = _order_display_status(order)
    return f"{status} - {order.total_amount} {order.currency}" if order.total_amount is not None else status


def _order_display_status(order: Order) -> str:
    status = order.status.value.replace("_", " ").title()
    if order.status == OrderStatus.PAID:
        extra = order.extra_attrs or {}
        meta = extra.get(OXAPAY_EXTRA_KEY)
        if isinstance(meta, dict):
            fulfillment = meta.get("fulfillment")
            if isinstance(fulfillment, dict) and fulfillment.get("delivered_at"):
                return "Delivered"
    return status
