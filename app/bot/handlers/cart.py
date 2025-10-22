from __future__ import annotations

from decimal import Decimal
from typing import Optional

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.cart import (
    CART_BACK_CALLBACK,
    CART_CHECKOUT_CALLBACK,
    CART_CLEAR_CALLBACK,
    CART_QTY_PREFIX,
    CART_REFRESH_CALLBACK,
    CART_REMOVE_PREFIX,
    cart_menu_keyboard,
)
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.infrastructure.db.repositories import UserRepository
from app.services.cart_service import CartService
from app.services.product_service import ProductService

router = Router(name="cart")


@router.callback_query(F.data == MainMenuCallback.CART.value)
async def handle_cart_entry(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await _render_cart(callback, session)
    await callback.answer()


@router.callback_query(F.data == CART_REFRESH_CALLBACK)
async def handle_cart_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_cart(callback, session)
    await callback.answer()


@router.callback_query(F.data == CART_BACK_CALLBACK)
async def handle_cart_back(callback: CallbackQuery) -> None:
    await _safe_edit_message(
        callback.message,
        "Main menu",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == CART_CLEAR_CALLBACK)
async def handle_cart_clear(callback: CallbackQuery, session: AsyncSession) -> None:
    profile = await _ensure_profile(session, callback.from_user.id)
    cart_service = CartService(session)
    cart = await cart_service.get_active_cart(profile.id)
    if cart is not None:
        await cart_service.clear_cart(cart)
    await _render_cart(callback, session, notice="Cart cleared.")
    await callback.answer()


@router.callback_query(F.data.startswith(CART_REMOVE_PREFIX))
async def handle_cart_remove(callback: CallbackQuery, session: AsyncSession) -> None:
    product_id = int(callback.data.removeprefix(CART_REMOVE_PREFIX))
    profile = await _ensure_profile(session, callback.from_user.id)
    cart_service = CartService(session)
    cart = await cart_service.get_active_cart(profile.id)
    if cart is None:
        await callback.answer("Cart is already empty.", show_alert=True)
        return
    await cart_service.remove_product(cart, product_id)
    await _render_cart(callback, session, notice="Item removed.")
    await callback.answer()


@router.callback_query(F.data.startswith(CART_QTY_PREFIX))
async def handle_cart_quantity(callback: CallbackQuery, session: AsyncSession) -> None:
    action, raw_product_id = callback.data.removeprefix(CART_QTY_PREFIX).split(":", maxsplit=1)
    product_id = int(raw_product_id)
    profile = await _ensure_profile(session, callback.from_user.id)
    cart_service = CartService(session)
    cart = await cart_service.get_active_cart(profile.id)
    if cart is None:
        await callback.answer("Cart is empty.", show_alert=True)
        return
    product = await cart_service.fetch_product(product_id)
    if product is None:
        await callback.answer("Product not found.", show_alert=True)
        return
    if action == "inc":
        await cart_service.add_product(cart, product, quantity=1)
    elif action == "dec":
        current_qty = _current_quantity(cart, product_id)
        await cart_service.update_quantity(cart, product, max(0, current_qty - 1))
    else:
        await callback.answer()
        return
    await _render_cart(callback, session)
    await callback.answer()


@router.callback_query(F.data == CART_CHECKOUT_CALLBACK)
async def handle_cart_checkout(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    profile = await _ensure_profile(session, callback.from_user.id)
    cart_service = CartService(session)
    cart = await cart_service.get_active_cart(profile.id)
    if cart is None or not cart.items:
        await callback.answer("Cart is empty.", show_alert=True)
        await _render_cart(callback, session)
        return

    product_queue: list[int] = []
    for item in cart.items:
        product_queue.extend([item.product_id] * max(1, item.quantity))

    await state.update_data(
        cart_checkout_queue=product_queue,
        cart_checkout_index=0,
        cart_id=cart.id,
    )
    await callback.answer("Starting checkout...")
    product_service = ProductService(session)
    first_product = await product_service.get_product(product_queue[0])
    if first_product is None:
        await _render_cart(callback, session, notice="First product unavailable; please refresh.")
        return

    await _start_product_flow(callback, session, state, first_product.id, origin="cart")


def _current_quantity(cart, product_id: int) -> int:
    for item in cart.items:
        if item.product_id == product_id:
            return item.quantity
    return 0


async def _render_cart(callback: CallbackQuery, session: AsyncSession, notice: Optional[str] = None) -> None:
    profile = await _ensure_profile(session, callback.from_user.id)
    cart_service = CartService(session)
    cart = await cart_service.get_active_cart(profile.id)
    if cart is None:
        cart = await cart_service.get_or_create_cart(user_id=profile.id, currency=_default_currency())
    totals = await cart_service.refresh_totals(cart)

    text_lines = ["<b>Your shopping cart</b>"]
    if notice:
        text_lines.append(f"- {notice}")
        text_lines.append("")

    if not cart.items:
        text_lines.append("Cart is empty. Visit Products to add items.")
    else:
        for idx, item in enumerate(cart.items, start=1):
            title = item.title_override or getattr(item.product, "name", "Item")
            text_lines.append(f"{idx}. {title} x{item.quantity} — {item.total_amount} {item.currency}")
        text_lines.append("")
        text_lines.append(f"Subtotal: {totals.subtotal} {cart.currency}")
        if totals.discount > Decimal("0"):
            text_lines.append(f"Discounts: -{totals.discount} {cart.currency}")
        if totals.tax > Decimal("0"):
            text_lines.append(f"Tax: {totals.tax} {cart.currency}")
        if totals.shipping > Decimal("0"):
            text_lines.append(f"Shipping: {totals.shipping} {cart.currency}")
        text_lines.append(f"<b>Total: {totals.total} {cart.currency}</b>")

    await _safe_edit_message(
        callback.message,
        "\n".join(text_lines),
        reply_markup=cart_menu_keyboard(cart, totals.total),
    )


def _default_currency() -> str:
    from app.core.config import get_settings

    return get_settings().payment_currency


async def _safe_edit_message(message, text: str, *, reply_markup=None) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await message.answer(text, reply_markup=reply_markup)


async def _ensure_profile(session: AsyncSession, telegram_id: int):
    profile = await UserRepository(session).get_by_telegram_id(telegram_id)
    if profile is None:
        raise RuntimeError("User profile not found.")
    return profile


def _user_is_owner(user_id: int | None) -> bool:
    from app.core.config import get_settings

    if user_id is None:
        return False
    return user_id in (get_settings().owner_user_ids or [])


async def _start_product_flow(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    product_id: int,
    *,
    origin: str,
) -> None:
    from app.bot.handlers.products import initiate_product_order_flow

    await initiate_product_order_flow(callback, session, state, product_id, origin=origin)
