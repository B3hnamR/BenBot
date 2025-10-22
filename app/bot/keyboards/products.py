from __future__ import annotations

from typing import Iterable

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.infrastructure.db.models import Product

PRODUCT_VIEW_PREFIX = "product:view:"
PRODUCT_ORDER_PREFIX = "product:order:"
PRODUCT_ADD_TO_CART_PREFIX = "product:add:"
PRODUCT_BACK_CALLBACK = "product:back"


def products_list_keyboard(products: Iterable[Product]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in products:
        builder.button(
            text=f"{product.name} - {product.price} {product.currency}",
            callback_data=f"{PRODUCT_VIEW_PREFIX}{product.id}",
        )
    builder.button(text="Back", callback_data=PRODUCT_BACK_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


def product_details_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Purchase", callback_data=f"{PRODUCT_ORDER_PREFIX}{product_id}")
    builder.button(text="Add to cart", callback_data=f"{PRODUCT_ADD_TO_CART_PREFIX}{product_id}")
    builder.button(text="Back to products", callback_data=PRODUCT_BACK_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()
