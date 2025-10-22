from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import order_manage_keyboard
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.keyboards.orders import (
    ORDER_CANCEL_CALLBACK,
    ORDER_CONFIRM_CALLBACK,
    order_confirm_keyboard,
)
from app.bot.keyboards.products import (
    PRODUCT_BACK_CALLBACK,
    PRODUCT_ADD_TO_CART_PREFIX,
    PRODUCT_ORDER_PREFIX,
    PRODUCT_VIEW_PREFIX,
    product_details_keyboard,
    products_list_keyboard,
)
from app.bot.states.order import OrderFlowState
from app.core.config import get_settings
from app.core.enums import OrderStatus, ProductQuestionType
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories import UserRepository
from app.services.cart_service import CartService
from app.services.config_service import ConfigService
from app.services.crypto_payment_service import (
    CryptoInvoiceResult,
    CryptoPaymentService,
)
from app.services.order_service import OrderCreationError, OrderService
from app.services.product_service import ProductService


router = Router(name="products")


async def initiate_product_order_flow(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    product_id: int,
    *,
    origin: str,
) -> bool:
    product_service = ProductService(session)
    product = await product_service.get_product(product_id)
    if product is None or not product.is_active:
        await _safe_edit_message(
            callback.message,
            "The selected product is no longer available.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return False

    questions = [
        {
            "id": question.id,
            "key": question.field_key,
            "prompt": question.prompt,
            "help": question.help_text,
            "type": question.question_type.value,
            "required": question.is_required,
            "config": question.config or {},
        }
        for question in product.questions or []
    ]

    state_data = await state.get_data()
    cart_queue = state_data.get("cart_checkout_queue") if origin != "direct" else None
    cart_index = state_data.get("cart_checkout_index", 0) if cart_queue else 0
    cart_id = state_data.get("cart_id") if cart_queue else None

    await state.set_state(OrderFlowState.collecting_answer)
    await state.update_data(
        product_id=product.id,
        product_name=product.name,
        price=str(product.price),
        currency=product.currency,
        questions=questions,
        question_index=0,
        answers=[],
        origin=origin,
        cart_checkout_queue=cart_queue,
        cart_checkout_index=cart_index,
        cart_id=cart_id,
    )

    if questions:
        await _prompt_question(callback.message, questions[0])
    else:
        await _show_order_confirmation(callback.message, state)
        await state.set_state(OrderFlowState.confirm)
    return True


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


@router.callback_query(F.data.startswith(PRODUCT_ADD_TO_CART_PREFIX))
async def handle_add_to_cart(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    product_id = int(callback.data.removeprefix(PRODUCT_ADD_TO_CART_PREFIX))
    product_service = ProductService(session)
    product = await product_service.get_product(product_id)
    if product is None or not product.is_active:
        await callback.answer("Product unavailable.", show_alert=True)
        return

    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await callback.answer("User profile not found.", show_alert=True)
        return

    cart_service = CartService(session)
    cart = await cart_service.get_or_create_cart(user_id=profile.id, currency=product.currency)
    await cart_service.add_product(cart, product, quantity=1)
    await cart_service.refresh_totals(cart)

    await callback.answer("Added to cart")
    await callback.message.answer(
        f"? <b>{product.name}</b> added to cart.\nTotal items: {len(cart.items)}",
    )


@router.callback_query(F.data.startswith(PRODUCT_ORDER_PREFIX))
async def handle_product_order(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if await state.get_state() is not None:
        await callback.answer("Finish the current operation first.", show_alert=True)
        return

    product_id = int(callback.data.removeprefix(PRODUCT_ORDER_PREFIX))
    await initiate_product_order_flow(callback, session, state, product_id, origin="direct")
    await callback.answer()


@router.message(OrderFlowState.collecting_answer)
async def collect_order_answer(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await _cancel_order_flow(message, state, "Order cancelled.")
        return

    data = await state.get_data()
    questions: List[dict[str, Any]] = data.get("questions", [])
    index: int = data.get("question_index", 0)

    if index >= len(questions):
        await _show_order_confirmation(message, state)
        await state.set_state(OrderFlowState.confirm)
        return

    question = questions[index]

    if not text:
        await message.answer("Please send a text response or /cancel.")
        return

    if text.lower() == "/skip":
        if question["required"]:
            await message.answer("This field is required.")
            return
        answer_value: str | None = None
    else:
        try:
            answer_value = _validate_answer(question, text)
        except ValueError as exc:
            await message.answer(str(exc))
            return

    answers = list(data.get("answers", []))
    answers.append(
        {
            "key": question["key"],
            "prompt": question["prompt"],
            "value": answer_value,
            "type": question["type"],
        }
    )

    index += 1
    await state.update_data(answers=answers, question_index=index)

    if index >= len(questions):
        await _show_order_confirmation(message, state)
        await state.set_state(OrderFlowState.confirm)
    else:
        await _prompt_question(message, questions[index])


@router.callback_query(OrderFlowState.confirm, F.data == ORDER_CONFIRM_CALLBACK)
async def finalize_order(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    product_id: int = data["product_id"]
    product_name: str = data.get("product_name", "Product")
    answers: List[dict[str, str | None]] = list(data.get("answers", []))
    origin: str = data.get("origin", "direct")
    cart_queue: list[int] | None = data.get("cart_checkout_queue")
    cart_index: int = int(data.get("cart_checkout_index", 0))
    cart_id = data.get("cart_id")

    order_service = OrderService(session)
    product = await order_service.get_product(product_id)
    if product is None or not product.is_active:
        await state.clear()
        await callback.answer("Product is not available", show_alert=True)
        await _safe_edit_message(callback.message, "Order cancelled.")
        return

    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await state.clear()
        await callback.answer("Unable to locate user profile.", show_alert=True)
        return

    config_service = ConfigService(session)
    timeout_minutes = await config_service.invoice_timeout_minutes()

    answer_pairs = [(item["key"], item.get("value")) for item in answers]

    try:
        order = await order_service.create_order(
            user_id=profile.id,
            product=product,
            answers=answer_pairs,
            invoice_timeout_minutes=timeout_minutes,
        )
    except OrderCreationError as exc:
        await state.clear()
        await callback.answer(str(exc), show_alert=True)
        return

    crypto_service = CryptoPaymentService(session)
    crypto_result = await crypto_service.create_invoice_for_order(
        order,
        description=f"{product.name} ({order.public_id})",
        email=_extract_email_from_answers(answers),
    )

    # If this order originates from a cart checkout, update cart state.
    cart_service: CartService | None = None
    cart = None
    if origin != "direct" and cart_queue:
        cart_service = CartService(session)
        cart = await cart_service.get_active_cart(profile.id)
        if cart is not None:
            product_obj = await cart_service.fetch_product(product_id)
            if product_obj is not None:
                current_qty = _cart_quantity(cart, product_id)
                new_qty = max(0, current_qty - 1)
                await cart_service.update_quantity(cart, product_obj, new_qty)

        next_index = cart_index + 1
        if next_index < len(cart_queue):
            await state.update_data(
                cart_checkout_queue=cart_queue,
                cart_checkout_index=next_index,
                cart_id=cart_id,
                origin="cart",
            )
        else:
            if cart is not None:
                await cart_service.clear_cart(cart)
            await state.clear()
    else:
        await state.clear()

    await _safe_edit_message(
        callback.message,
        _order_confirmation_message(order, product_name, answers, crypto_result),
        reply_markup=_order_confirmation_keyboard(crypto_result),
    )
    await callback.answer("Order created")

    await _notify_admins_of_order(callback, order, product_name, answers, crypto_result)

    if origin != "direct" and cart_queue:
        next_index = cart_index + 1
        if next_index < len(cart_queue):
            next_product_id = cart_queue[next_index]
            await initiate_product_order_flow(callback, session, state, next_product_id, origin="cart")
            return
        else:
            await callback.message.answer("Cart checkout complete. All items processed.")
            return


@router.callback_query(OrderFlowState.confirm, F.data == ORDER_CANCEL_CALLBACK)
async def cancel_order_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit_message(callback.message, "Order cancelled.")
    await callback.answer()


@router.callback_query(F.data == ORDER_CANCEL_CALLBACK)
async def ignore_cancel(callback: CallbackQuery) -> None:
    await callback.answer()


async def _prompt_question(message: Message, question: dict[str, Any]) -> None:
    lines = [f"<b>{question['prompt']}</b>"]
    if question.get("help"):
        lines.append(question["help"])
    qtype = question["type"]
    options = question.get("config", {}).get("options")
    if qtype in {ProductQuestionType.SELECT.value, ProductQuestionType.MULTISELECT.value} and options:
        joined = ", ".join(options)
        if qtype == ProductQuestionType.SELECT.value:
            lines.append(f"Options: {joined}")
        else:
            lines.append(f"Select one or more (comma separated): {joined}")
    if not question["required"]:
        lines.append("Send /skip to leave empty.")
    lines.append("Send /cancel to abort.")
    await message.answer("\n".join(lines))


async def _show_order_confirmation(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_name = data.get("product_name")
    price = data.get("price")
    currency = data.get("currency")
    answers: List[dict[str, str | None]] = list(data.get("answers", []))

    lines = [
        f"<b>{product_name}</b>",
        f"Amount: {price} {currency}",
        "",
        "<b>Order details</b>",
    ]

    if not answers:
        lines.append("No additional information requested.")
    else:
        for item in answers:
            display = item.get("value") or "-"
            lines.append(f"{item['prompt']}: {display}")

    await message.answer("\n".join(lines), reply_markup=order_confirm_keyboard())


def _validate_answer(question: dict[str, Any], value: str) -> str:
    qtype = question["type"]
    if qtype == ProductQuestionType.EMAIL.value:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")
        return value.strip()

    if qtype == ProductQuestionType.PHONE.value:
        cleaned = value.replace(" ", "")
        if not re.fullmatch(r"[+\d][\d\-]{4,32}", cleaned):
            raise ValueError("Enter a valid phone number.")
        return value.strip()

    if qtype == ProductQuestionType.NUMBER.value:
        try:
            Decimal(value)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Enter a valid number.") from exc
        return value.strip()

    if qtype == ProductQuestionType.SELECT.value:
        options = [opt.strip() for opt in question.get("config", {}).get("options", [])]
        match = next((opt for opt in options if opt.lower() == value.lower()), None)
        if match is None:
            raise ValueError("Select one of the provided options.")
        return match

    if qtype == ProductQuestionType.MULTISELECT.value:
        options = [opt.strip() for opt in question.get("config", {}).get("options", [])]
        provided = [item.strip() for item in value.split(",") if item.strip()]
        if not provided:
            raise ValueError("Select at least one option.")
        normalized: list[str] = []
        for item in provided:
            match = next((opt for opt in options if opt.lower() == item.lower()), None)
            if match is None:
                raise ValueError("One or more options are invalid.")
            if match not in normalized:
                normalized.append(match)
        return ", ".join(normalized)

    return value.strip()


def _order_confirmation_message(
    order: Order,
    product_name: str,
    answers: list[dict[str, str | None]],
    crypto: CryptoInvoiceResult | None,
) -> str:
    expires_text = ""
    if order.payment_expires_at:
        remaining = order.payment_expires_at - datetime.now(tz=timezone.utc)
        minutes = max(0, int(remaining.total_seconds() // 60))
        expires_text = (
            "\nPayment deadline: "
            f"{order.payment_expires_at:%Y-%m-%d %H:%M UTC}"
            f" (about {minutes} minutes left)."
        )

    lines = [
        "<b>Order created!</b>",
        f"Product: {product_name}",
        f"Order ID: <code>{order.public_id}</code>",
        f"Status: {order.status.value.replace('_', ' ').title()}",
        f"Total: {order.total_amount} {order.currency}",
    ]
    if order.invoice_payload:
        lines.append(f"Payment reference: <code>{order.invoice_payload}</code>")
    if answers:
        lines.append("")
        lines.append("<b>Your details</b>")
        for item in answers:
            lines.append(f"{item['prompt']}: {item.get('value') or '-'}")
    if expires_text:
        lines.append(expires_text)
    if crypto is not None:
        if crypto.error:
            lines.append("")
            lines.append(f"?? Crypto payment issue: {crypto.error}")
        elif crypto.enabled:
            lines.append("")
            lines.append("<b>Pay with crypto</b>")
            if crypto.pay_link:
                lines.append(f'<a href="{crypto.pay_link}">Open crypto checkout</a>')
            if crypto.track_id:
                lines.append(f"Track ID: <code>{crypto.track_id}</code>")
            if crypto.status:
                lines.append(f"Last known status: {crypto.status}")
    lines.append("\nPlease follow the payment instructions provided by the team.")
    return "\n".join(lines)


async def _cancel_order_flow(message: Message, state: FSMContext, text: str) -> None:
    await state.clear()
    await message.answer(text)


async def _notify_admins_of_order(
    callback: CallbackQuery,
    order: Order,
    product_name: str,
    answers: list[dict[str, str | None]],
    crypto: CryptoInvoiceResult | None = None,
) -> None:
    settings = get_settings()
    if not settings.owner_user_ids:
        return

    lines = [
        "<b>New order received</b>",
        f"Order ID: <code>{order.public_id}</code>",
        f"User: <code>{callback.from_user.id}</code> ({callback.from_user.username or '-'})",
        f"Product: {product_name}",
        f"Total: {order.total_amount} {order.currency}",
        f"Status: {order.status.value}",
    ]
    if order.invoice_payload:
        lines.append(f"Reference: <code>{order.invoice_payload}</code>")
    if answers:
        lines.append("")
        lines.append("<b>Answers</b>")
        for item in answers:
            lines.append(f"{item['key']}: {item.get('value') or '-'}")
    if crypto is not None:
        lines.append("")
        lines.append("<b>Crypto payment</b>")
        if crypto.track_id:
            lines.append(f"Track ID: {crypto.track_id}")
        if crypto.pay_link:
            lines.append(f"Link: {crypto.pay_link}")
        if crypto.status:
            lines.append(f"Status: {crypto.status}")
        if crypto.error:
            lines.append(f"Error: {crypto.error}")

    payload = "\n".join(lines)
    tasks = []
    for owner_id in settings.owner_user_ids:
        tasks.append(
            callback.bot.send_message(
                owner_id,
                payload,
                reply_markup=order_manage_keyboard(order),
                disable_web_page_preview=True,
            )
        )
    await asyncio.gather(*tasks)


def _order_confirmation_keyboard(crypto: CryptoInvoiceResult | None):
    if crypto is None or not crypto.enabled or not crypto.pay_link:
        builder = InlineKeyboardBuilder()
        builder.button(text="Back to menu", callback_data=MainMenuCallback.PRODUCTS.value)
        builder.adjust(1)
        return builder.as_markup()
    builder = InlineKeyboardBuilder()
    builder.button(text="Pay with crypto", url=crypto.pay_link)
    builder.button(text="Back to menu", callback_data=MainMenuCallback.PRODUCTS.value)
    builder.adjust(1)
    return builder.as_markup()


def _extract_email_from_answers(answers: list[dict[str, str | None]]) -> str | None:
    for item in answers:
        value = (item.get("value") or "").strip()
        if not value:
            continue
        if item.get("type") == ProductQuestionType.EMAIL.value:
            return value
        key = (item.get("key") or "").lower()
        prompt = (item.get("prompt") or "").lower()
        if "email" in key or "email" in prompt or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
                return value
    return None


def _cart_quantity(cart, product_id: int) -> int:
    for item in cart.items:
        if item.product_id == product_id:
            return item.quantity
    return 0

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
