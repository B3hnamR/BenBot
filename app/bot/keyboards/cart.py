from __future__ import annotations

from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.infrastructure.db.models import CartItem, ShoppingCart

CART_REFRESH_CALLBACK = "cart:refresh"
CART_CLEAR_CALLBACK = "cart:clear"
CART_CHECKOUT_CALLBACK = "cart:checkout"
CART_BACK_CALLBACK = "cart:back"
CART_REMOVE_PREFIX = "cart:remove:"
CART_QTY_PREFIX = "cart:qty:"
CART_CONFIRM_ORDER = "cart:confirm_order"
CART_CANCEL_CHECKOUT = "cart:cancel_checkout"


def cart_menu_keyboard(cart: ShoppingCart, totals: Decimal) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for item in cart.items:
        builder.button(
            text=_item_label(item),
            callback_data=f"{CART_QTY_PREFIX}show:{item.product_id}",
        )
        builder.row(
            InlineKeyboardButton(text="-", callback_data=f"{CART_QTY_PREFIX}dec:{item.product_id}"),
            InlineKeyboardButton(text="+", callback_data=f"{CART_QTY_PREFIX}inc:{item.product_id}"),
            InlineKeyboardButton(text="Remove", callback_data=f"{CART_REMOVE_PREFIX}{item.product_id}"),
        )

    if not cart.items:
        builder.button(text="Cart is empty", callback_data=CART_REFRESH_CALLBACK)
    else:
        builder.button(text=f"Checkout ({totals} {cart.currency})", callback_data=CART_CHECKOUT_CALLBACK)
        builder.button(text="Clear cart", callback_data=CART_CLEAR_CALLBACK)
    builder.button(text="Refresh", callback_data=CART_REFRESH_CALLBACK)
    builder.button(text="Back to menu", callback_data=CART_BACK_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


def _item_label(item: CartItem) -> str:
    title = item.title_override or getattr(item.product, "name", "Item")
    return f"{title} x{item.quantity} - {item.total_amount} {item.currency}"


def cart_checkout_confirmation_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Confirm order", callback_data=CART_CONFIRM_ORDER)
    builder.button(text="Cancel checkout", callback_data=CART_CANCEL_CHECKOUT)
    builder.adjust(1)
    return builder.as_markup()
