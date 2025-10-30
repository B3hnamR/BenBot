from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

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
    CART_CONFIRM_ORDER,
    CART_CANCEL_CHECKOUT,
    cart_menu_keyboard,
    cart_checkout_confirmation_keyboard,
)
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.infrastructure.db.repositories import OrderRepository, UserRepository
from app.services.cart_service import CartService
from app.services.config_service import ConfigService
from app.services.coupon_service import CouponService
from app.services.product_service import ProductService
from app.services.order_service import OrderService
from app.services.loyalty_order_service import (
    ensure_points_available,
    reserve_loyalty_for_order,
)
from app.services.crypto_payment_service import CryptoPaymentService
from app.bot.states.order import OrderFlowState

router = Router(name="cart")

CURRENCY_QUANT = Decimal("0.01")


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
    try:
        if action == "inc":
            await cart_service.add_product(cart, product, quantity=1)
        elif action == "dec":
            current_qty = _current_quantity(cart, product_id)
            await cart_service.update_quantity(cart, product, max(0, current_qty - 1))
        else:
            await callback.answer()
            return
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
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

    totals = await cart_service.refresh_totals(cart)
    items_snapshot = []
    for item in cart.items:
        title = item.title_override or getattr(item.product, "name", "Item")
        items_snapshot.append(
            {
                "product_id": item.product_id,
                "name": title,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "total_amount": str(item.total_amount),
                "currency": item.currency,
            }
        )

    totals_payload = {
        "subtotal": str(totals.subtotal),
        "discount": str(totals.discount),
        "tax": str(totals.tax),
        "shipping": str(totals.shipping),
        "total": str(totals.total),
    }

    await state.update_data(
        cart_checkout_queue=items_snapshot,
        cart_checkout_index=0,
        cart_answers=[],
        cart_totals=dict(totals_payload),
        cart_totals_base=dict(totals_payload),
        cart_currency=cart.currency,
        cart_id=cart.id,
        cart_summary_message_chat=None,
        cart_summary_message_id=None,
        coupon_prompt_status=None,
        coupon_code=None,
        coupon_discount_value=None,
        coupon_id=None,
        coupon_mode="cart",
        coupon_base_amount=str(totals_payload.get("total", totals_payload.get("subtotal", "0"))),
        loyalty_prompt_status=None,
        loyalty_redeem_points=None,
        loyalty_redeem_value=None,
        loyalty_total_due=None,
        loyalty_mode=None,
    )

    await callback.answer("Starting checkout...")
    product_service = ProductService(session)
    first_product = await product_service.get_product(items_snapshot[0]["product_id"])
    if first_product is None:
        await _render_cart(callback, session, notice="First product unavailable; please refresh.")
        return

    await _start_product_flow(callback, session, state, first_product.id, origin="cart", item_index=0)


@router.callback_query(OrderFlowState.cart_confirm, F.data == CART_CONFIRM_ORDER)
async def handle_cart_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    cart_queue = data.get("cart_checkout_queue") or []
    totals = data.get("cart_totals") or {}
    answers = data.get("cart_answers") or []
    currency = data.get("cart_currency") or "USD"

    if not cart_queue:
        await callback.answer("Cart is empty.", show_alert=True)
        await state.clear()
        await _render_cart(callback, session)
        return

    profile = await _ensure_profile(session, callback.from_user.id)
    order_service = OrderService(session)
    product = await order_service.get_product(cart_queue[0]["product_id"])
    if product is None:
        await callback.answer("A product in your cart is no longer available.", show_alert=True)
        await state.clear()
        await _render_cart(callback, session)
        return

    config_service = ConfigService(session)
    timeout_minutes = await config_service.invoice_timeout_minutes()

    totals_base = data.get("cart_totals_base") or {}
    base_total = Decimal(str(totals_base.get("total") or totals.get("total") or "0")).quantize(
        CURRENCY_QUANT,
        rounding=ROUND_HALF_UP,
    )

    coupon_code = (data.get("coupon_code") or "").strip() or None
    coupon_discount_state = Decimal(str(data.get("coupon_discount_value") or "0")).quantize(
        CURRENCY_QUANT,
        rounding=ROUND_HALF_UP,
    )
    coupon_meta: dict[str, Any] | None = None
    coupon_discount = Decimal("0")
    coupon_warning = False
    coupon = None
    coupon_service = CouponService(session)

    if coupon_code:
        coupon = await coupon_service.get_coupon(coupon_code)
        if coupon is None:
            coupon_warning = True
        else:
            try:
                await coupon_service.validate_coupon(coupon, user_id=profile.id, order_total=base_total)
            except ValueError:
                coupon_warning = True
            else:
                coupon_discount = coupon_service.calculate_discount(coupon, base_total).quantize(
                    CURRENCY_QUANT,
                    rounding=ROUND_HALF_UP,
                )
                coupon_discount = min(coupon_discount, base_total)
                if coupon_discount > Decimal("0"):
                    coupon_meta = {
                        "code": coupon.code,
                        "discount": str(coupon_discount),
                        "status": "pending",
                    }
                else:
                    coupon_discount = Decimal("0")
    if coupon_discount == Decimal("0") and coupon_discount_state > Decimal("0") and not coupon_warning:
        coupon_discount = coupon_discount_state

    total_after_coupon = max(Decimal("0"), base_total - coupon_discount)

    loyalty_points = int(data.get("loyalty_redeem_points") or 0)
    loyalty_value = Decimal(str(data.get("loyalty_redeem_value") or "0")).quantize(
        CURRENCY_QUANT,
        rounding=ROUND_HALF_UP,
    )
    ratio = Decimal(str(data.get("loyalty_ratio") or "0")) if loyalty_points else Decimal("0")
    total_due = Decimal(str(data.get("loyalty_total_due") or total_after_coupon)).quantize(
        CURRENCY_QUANT,
        rounding=ROUND_HALF_UP,
    )

    loyalty_warning = False
    if loyalty_points > 0:
        can_redeem = await ensure_points_available(session, profile.id, points=loyalty_points)
        if not can_redeem:
            loyalty_warning = True
            loyalty_points = 0
            loyalty_value = Decimal("0")
            total_due = total_after_coupon
    if loyalty_points == 0 or loyalty_value <= Decimal("0"):
        loyalty_points = 0
        loyalty_value = Decimal("0")
        total_due = total_after_coupon
    else:
        total_due = max(Decimal("0"), min(total_due, total_after_coupon))
        if ratio <= Decimal("0"):
            ratio = (loyalty_value / Decimal(loyalty_points)).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)

    totals["coupon_discount"] = str(coupon_discount)
    totals["loyalty_discount"] = str(loyalty_value)
    totals["total"] = str(total_due)
    await state.update_data(
        cart_totals=totals,
        coupon_discount_value=str(coupon_discount),
        loyalty_redeem_points=loyalty_points,
        loyalty_redeem_value=str(loyalty_value),
        loyalty_total_due=str(total_due),
    )

    loyalty_meta: dict[str, Any] | None = None
    if loyalty_points > 0 and loyalty_value > Decimal("0"):
        loyalty_meta = {
            "redeem": {
                "points": loyalty_points,
                "value": str(loyalty_value),
                "ratio": str(ratio),
                "currency": currency,
                "status": "pending",
            }
        }

    extra_attrs: dict[str, Any] = {
        "cart_items": cart_queue,
        "cart_answers": answers,
        "cart_totals": totals,
    }
    if loyalty_meta:
        extra_attrs["loyalty"] = loyalty_meta
    if coupon_meta:
        extra_attrs["coupon"] = coupon_meta

    total_amount = total_due

    order = await order_service.create_order(
        user_id=profile.id,
        product=product,
        answers=[],
        invoice_timeout_minutes=timeout_minutes,
        total_override=total_amount,
        currency_override=currency,
        extra_attrs=extra_attrs,
    )

    loyalty_meta_reserved = loyalty_meta
    if loyalty_points > 0 and loyalty_value > Decimal("0"):
        try:
            loyalty_meta_reserved = await reserve_loyalty_for_order(
                session,
                order,
                profile.id,
                points=loyalty_points,
                value=loyalty_value,
                ratio=ratio,
                currency=currency,
            )
        except ValueError:
            loyalty_warning = True
            loyalty_meta_reserved = loyalty_meta or {}
            redeem_meta = loyalty_meta_reserved.setdefault("redeem", {})
            redeem_meta.update(
                {
                    "points": loyalty_points,
                    "value": str(loyalty_value),
                    "ratio": str(ratio),
                    "currency": currency,
                    "status": "failed",
                }
            )
            await OrderRepository(session).merge_extra_attrs(order, {"loyalty": loyalty_meta_reserved})
            order.extra_attrs = order.extra_attrs or {}
            order.extra_attrs["loyalty"] = loyalty_meta_reserved

    if coupon_meta and coupon is not None and coupon_discount > Decimal("0"):
        try:
            await coupon_service.apply_coupon(
                coupon,
                user_id=profile.id,
                order_id=order.id,
                order_total=base_total,
            )
            coupon_meta["status"] = "reserved"
        except ValueError:
            coupon_warning = True
            coupon_meta["status"] = "failed"
        await OrderRepository(session).merge_extra_attrs(order, {"coupon": coupon_meta})
        order.extra_attrs = order.extra_attrs or {}
        order.extra_attrs["coupon"] = coupon_meta

    email = _extract_cart_email(answers)
    crypto_service = CryptoPaymentService(session)
    crypto_result = await crypto_service.create_invoice_for_order(
        order,
        description=f"Cart order ({order.public_id})",
        email=email,
    )

    cart_service = CartService(session)
    cart = await cart_service.get_active_cart(profile.id)
    if cart is not None:
        await cart_service.clear_cart(cart)

    summary_text = _format_cart_summary(cart_queue, totals, currency, include_header=True)
    admin_summary = "; ".join(f"{item['name']} x{item['quantity']}" for item in cart_queue)
    admin_answers = [{"key": "Cart items", "prompt": "Cart items", "value": admin_summary}]
    if coupon_discount > Decimal("0") and coupon_meta:
        admin_answers.append(
            {
                "key": "Coupon discount",
                "prompt": "Coupon discount",
                "value": f"-{coupon_discount} {currency} ({coupon_meta.get('code')})",
            }
        )
    if loyalty_points > 0 and loyalty_value > Decimal("0"):
        admin_answers.append(
            {
                "key": "Loyalty discount",
                "prompt": "Loyalty discount",
                "value": f"{loyalty_value} {currency} ({loyalty_points} pts)",
            }
        )

    from app.bot.handlers.products import _order_confirmation_keyboard, _notify_admins_of_order

    await _safe_edit_message(
        callback.message,
        "\n".join(
            [
                "<b>Cart order created!</b>",
                f"Order ID: <code>{order.public_id}</code>",
                f"Total: {total_amount} {currency}",
                "",
                summary_text,
            ]
        ),
        reply_markup=_order_confirmation_keyboard(crypto_result),
    )

    await _notify_admins_of_order(
        callback,
        order,
        "Cart order",
        admin_answers,
        crypto_result,
    )

    if loyalty_warning:
        await callback.message.answer(
            "Loyalty points could not be applied because your available balance changed. No points were deducted."
        )
    if coupon_warning:
        await callback.message.answer(
            "Coupon could not be applied. It may be invalid, expired, or its usage limit has been reached."
        )

    await callback.answer("Order created")
    await state.clear()


@router.callback_query(OrderFlowState.cart_confirm, F.data == CART_CANCEL_CHECKOUT)
async def handle_cart_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _render_cart(callback, session, notice="Checkout cancelled.")
    await callback.answer()


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
            text_lines.append(f"{idx}. {title} x{item.quantity} - {item.total_amount} {item.currency}")
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


def _format_cart_summary(
    items: list[dict[str, str | int]],
    totals: dict[str, str],
    currency: str,
    *,
    include_header: bool = False,
) -> str:
    lines = []
    if include_header:
        lines.append("<b>Items</b>")
    for idx, item in enumerate(items, start=1):
        lines.append(
            f"{idx}. {item['name']} x{item['quantity']} - {item['total_amount']} {item['currency']}"
        )
    lines.append("")
    lines.append(f"Subtotal: {totals.get('subtotal', '0')} {currency}")
    if Decimal(totals.get("discount", "0")) > 0:
        lines.append(f"Discounts: -{totals.get('discount')} {currency}")
    if Decimal(totals.get("tax", "0")) > 0:
        lines.append(f"Tax: {totals.get('tax')} {currency}")
    if Decimal(totals.get("shipping", "0")) > 0:
        lines.append(f"Shipping: {totals.get('shipping')} {currency}")
    if Decimal(totals.get("coupon_discount", "0")) > 0:
        lines.append(f"Coupon discount: -{totals.get('coupon_discount')} {currency}")
    if Decimal(totals.get("loyalty_discount", "0")) > 0:
        lines.append(f"Loyalty discount: -{totals.get('loyalty_discount')} {currency}")
    lines.append(f"Total: {totals.get('total', '0')} {currency}")
    return "\n".join(lines)


def _extract_cart_email(cart_answers: list[dict]) -> Optional[str]:
    for entry in cart_answers or []:
        email = None
        for answer in entry.get("answers", []):
            value = answer.get("value")
            if value and "@" in value:
                email = value
                break
        if email:
            return email
    return None


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
    item_index: Optional[int] = None,
) -> None:
    from app.bot.handlers.products import initiate_product_order_flow

    await initiate_product_order_flow(
        callback,
        session,
        state,
        product_id,
        origin=origin,
        item_index=item_index,
    )
