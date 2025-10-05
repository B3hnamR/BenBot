from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.keyboards.products import (
    PRODUCT_BACK_CALLBACK,
    PRODUCT_ORDER_PREFIX,
    PRODUCT_VIEW_PREFIX,
    product_details_keyboard,
    products_list_keyboard,
)
from app.core.config import get_settings
from app.services.product_service import ProductService


router = Router(name="products")


@router.callback_query(F.data == MainMenuCallback.PRODUCTS.value)
async def handle_show_products(callback: CallbackQuery, session: AsyncSession) -> None:
    service = ProductService(session)
    products = await service.list_active_products()

    if not products:
        await _safe_edit_message(
            callback.message,
            "No products are available yet. Please check back soon.",
            reply_markup=main_menu_keyboard(
                show_admin=_user_is_owner(callback.from_user.id)
            ),
        )
        await callback.answer()
        return

    await _safe_edit_message(
        callback.message,
        text="Choose a product to view details:",
        reply_markup=products_list_keyboard(products),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(PRODUCT_VIEW_PREFIX))
async def handle_view_product(callback: CallbackQuery, session: AsyncSession) -> None:
    product_id = int(callback.data.removeprefix(PRODUCT_VIEW_PREFIX))
    service = ProductService(session)
    product = await service.get_product(product_id)

    if product is None or not product.is_active:
        await callback.answer("Product is not available", show_alert=True)
        return

    text_lines = [
        f"<b>{product.name}</b>",
        f"Price: {product.price} {product.currency}",
    ]
    if product.summary:
        text_lines.append(product.summary)
    if product.description:
        text_lines.append(product.description)

    body = "\n\n".join(text_lines)
    await _safe_edit_message(
        callback.message,
        body,
        reply_markup=product_details_keyboard(product.id),
    )
    await callback.answer()


@router.callback_query(F.data == PRODUCT_BACK_CALLBACK)
async def handle_products_back(callback: CallbackQuery) -> None:
    await _safe_edit_message(
        callback.message,
        "Main menu",
        reply_markup=main_menu_keyboard(
            show_admin=_user_is_owner(callback.from_user.id)
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(PRODUCT_ORDER_PREFIX))
async def handle_product_order(callback: CallbackQuery) -> None:
    await callback.answer("Order flow is under construction.", show_alert=True)


async def _safe_edit_message(message, text: str, *, reply_markup=None) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        details = (exc.message or "").lower()
        if "message is not modified" not in details:
            raise


def _user_is_owner(user_id: int) -> bool:
    settings = get_settings()
    return user_id in settings.owner_user_ids
