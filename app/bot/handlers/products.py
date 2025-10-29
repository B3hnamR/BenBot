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
from app.bot.keyboards.cart import cart_checkout_confirmation_keyboard
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
    item_index: int | None = None,
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
    cart_index = item_index if item_index is not None else state_data.get("cart_checkout_index", 0)
    cart_answers = state_data.get("cart_answers", []) if origin != "direct" else None
    cart_totals = state_data.get("cart_totals") if origin != "direct" else None
    cart_currency = state_data.get("cart_currency") if origin != "direct" else None

    update_payload: dict[str, Any] = {
        "product_id": product.id,
        "product_name": product.name,
        "price": str(product.price),
        "currency": product.currency,
        "questions": questions,
        "origin": origin,
        "cart_checkout_index": cart_index,
        "cart_answers": cart_answers or [],
        "cart_totals": cart_totals,
        "cart_currency": cart_currency,
    }

    if origin != "direct" and cart_queue:
        quantity = _resolve_cart_quantity(cart_queue, cart_index)
        update_payload.update({
            "quantity": quantity,
            "question_index": 0,
            "answers": [],
        })
        await state.update_data(**update_payload)
        await _begin_question_flow(callback.message, state, quantity)
        return True

    existing_quantity = state_data.get("quantity")
    update_payload.update({
        "quantity": existing_quantity,
        "question_index": 0,
        "answers": [],
    })
    await state.update_data(**update_payload)

    if existing_quantity is None:
        await state.set_state(OrderFlowState.quantity)
        await _prompt_quantity(callback.message, product)
    else:
        await _begin_question_flow(callback.message, state, max(1, int(existing_quantity or 1)))
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
    try:
        await cart_service.add_product(cart, product, quantity=1)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await cart_service.refresh_totals(cart)

    await callback.answer("Added to cart")
    builder = InlineKeyboardBuilder()
    builder.button(text="View cart", callback_data=MainMenuCallback.CART.value)
    builder.button(text="Continue shopping", callback_data=MainMenuCallback.PRODUCTS.value)
    builder.adjust(1)
    await callback.message.answer(
        f"Cart update: <b>{product.name}</b> added.\nTotal items: {len(cart.items)}",
        reply_markup=builder.as_markup(),
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
        quantity = max(1, int(data.get("quantity", 1) or 1))
        try:
            answer_value = _validate_answer(question, text, quantity=quantity)
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
        quantity = max(1, int(data.get("quantity", 1) or 1))
        await _prompt_question(message, questions[index], quantity=quantity)


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
    cart_queue: list[dict] | None = data.get("cart_checkout_queue")
    cart_index: int = int(data.get("cart_checkout_index", 0))
    quantity: int = max(1, int(data.get("quantity", 1) or 1))

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

    if origin != "direct" and cart_queue:
        cart_answers = list(data.get("cart_answers", []))
        cart_answers.append({"product_id": product_id, "answers": answers})
        await state.update_data(cart_answers=cart_answers)

        next_index = cart_index + 1
        if next_index < len(cart_queue):
            next_item = cart_queue[next_index]
            await state.update_data(cart_checkout_index=next_index)
            await initiate_product_order_flow(
                callback,
                session,
                state,
                next_item["product_id"],
                origin="cart",
                item_index=next_index,
            )
            await callback.answer("Saved responses. Next item...")
            return

        totals = data.get("cart_totals") or {}
        currency = data.get("cart_currency") or product.currency
        summary_text = _format_cart_summary_for_confirmation(cart_queue, totals, currency)
        await state.set_state(OrderFlowState.cart_confirm)
        await _safe_edit_message(
            callback.message,
            summary_text,
            reply_markup=cart_checkout_confirmation_keyboard(),
        )
        await callback.answer("Review your cart and confirm.")
        return

    # Answer immediately to avoid Telegram timeout while we process payment setup.
    await callback.answer("Processing order...", cache_time=0)

    order_kwargs: dict[str, Any] = {
        "user_id": profile.id,
        "product": product,
        "answers": answer_pairs,
        "invoice_timeout_minutes": timeout_minutes,
        "extra_attrs": {"quantity": quantity},
    }
    if quantity > 1:
        order_kwargs["total_override"] = Decimal(product.price) * quantity

    try:
        order = await order_service.create_order(**order_kwargs)
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

    await state.clear()

    display_answers = list(answers)
    if quantity > 1:
        display_answers.append({"key": "quantity", "prompt": "Quantity", "value": str(quantity)})

    await _safe_edit_message(
        callback.message,
        _order_confirmation_message(order, product_name, display_answers, crypto_result, quantity=quantity),
        reply_markup=_order_confirmation_keyboard(crypto_result),
    )
    await callback.message.answer("Order created. Check the message above for payment details.")

    await _notify_admins_of_order(callback, order, product_name, display_answers, crypto_result)

@router.callback_query(OrderFlowState.confirm, F.data == ORDER_CANCEL_CALLBACK)
async def cancel_order_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit_message(callback.message, "Order cancelled.")
    await callback.answer()


@router.callback_query(F.data == ORDER_CANCEL_CALLBACK)
async def ignore_cancel(callback: CallbackQuery) -> None:
    await callback.answer()


async def _prompt_question(
    message: Message,
    question: dict[str, Any],
    *,
    quantity: int = 1,
) -> None:
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
    if qtype == ProductQuestionType.EMAIL.value and quantity > 1:
        lines.append(f"Enter {quantity} email addresses, one per line (or separated by commas).")
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


def _validate_answer(question: dict[str, Any], value: str, *, quantity: int = 1) -> str:
    qtype = question["type"]
    if qtype == ProductQuestionType.EMAIL.value:
        entries = _split_multivalue(value, quantity)
        emails: list[str] = []
        for entry in entries:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", entry):
                raise ValueError("Enter valid email addresses (one per line).")
            emails.append(entry.strip())
        return "\n".join(emails)

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


def _split_multivalue(raw: str, quantity: int) -> list[str]:
    if quantity <= 1:
        return [raw.strip()]
    normalized = raw.replace(",", "\n")
    entries = [item.strip() for item in normalized.splitlines() if item.strip()]
    if len(entries) != quantity:
        raise ValueError(f"Enter {quantity} values, one per line.")
    return entries


def _order_confirmation_message(
    order: Order,
    product_name: str,
    answers: list[dict[str, str | None]],
    crypto: CryptoInvoiceResult | None,
    *,
    quantity: int = 1,
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
    if quantity > 1:
        lines.insert(3, f"Quantity: {quantity}")
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


async def _prompt_quantity(message: Message, product) -> None:
    lines = [
        f"<b>{product.name}</b>",
        "How many units would you like to purchase?",
        "Send an integer greater than zero.",
    ]
    if product.max_per_order is not None:
        lines.append(f"Maximum per order: {product.max_per_order}.")
    if product.inventory is not None:
        lines.append(f"In stock: {product.inventory}.")
    lines.append("Send /skip to keep quantity 1.")
    lines.append("Send /cancel to abort.")
    await message.answer("\n".join(lines))


async def _begin_question_flow(target_message: Message, state: FSMContext, quantity: int) -> None:
    quantity = max(1, quantity)
    await state.update_data(quantity=quantity, question_index=0, answers=[])
    await state.set_state(OrderFlowState.collecting_answer)
    data = await state.get_data()
    questions: List[dict[str, Any]] = data.get("questions", [])
    if questions:
        await _prompt_question(target_message, questions[0], quantity=quantity)
    else:
        await _show_order_confirmation(target_message, state)
        await state.set_state(OrderFlowState.confirm)


def _resolve_cart_quantity(cart_queue: list[dict[str, Any]], index: int) -> int:
    try:
        raw = cart_queue[index]["quantity"]
        quantity = int(raw)
    except (KeyError, ValueError, TypeError, IndexError):
        quantity = 1
    if quantity <= 0:
        quantity = 1
    return quantity


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


def _format_cart_summary_for_confirmation(items: list[dict], totals: dict[str, str], currency: str) -> str:
    lines: list[str] = ["<b>Cart checkout summary</b>", ""]
    for idx, item in enumerate(items, start=1):
        lines.append(f"{idx}. {item['name']} x{item['quantity']} - {item['total_amount']} {item['currency']}")
    lines.append("")
    subtotal = totals.get("subtotal", "0")
    discount = totals.get("discount", "0")
    tax = totals.get("tax", "0")
    shipping = totals.get("shipping", "0")
    total = totals.get("total", "0")
    lines.append(f"Subtotal: {subtotal} {currency}")
    if Decimal(discount or "0") > 0:
        lines.append(f"Discounts: -{discount} {currency}")
    if Decimal(tax or "0") > 0:
        lines.append(f"Tax: {tax} {currency}")
    if Decimal(shipping or "0") > 0:
        lines.append(f"Shipping: {shipping} {currency}")
    lines.append(f"Total: {total} {currency}")
    lines.append("")
    lines.append("Confirm to create a combined order for all items.")
    return "\n".join(lines)

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
@router.message(OrderFlowState.quantity)
async def collect_order_quantity(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await _cancel_order_flow(message, state, "Order cancelled.")
        return

    if text.lower() in {"", "/skip"}:
        quantity = 1
    else:
        if not text.isdigit():
            await message.answer("Enter a valid quantity (integer greater than zero).")
            return
        quantity = int(text)
        if quantity <= 0:
            await message.answer("Quantity must be greater than zero.")
            return

    data = await state.get_data()
    product_id = data.get("product_id")
    if not product_id:
        await _cancel_order_flow(message, state, "Order data lost. Please start again.")
        return

    order_service = OrderService(session)
    product = await order_service.get_product(product_id)
    if product is None or not product.is_active:
        await _cancel_order_flow(message, state, "Product is not available.")
        return

    if product.max_per_order is not None and quantity > product.max_per_order:
        await message.answer(
            f"You can purchase up to {product.max_per_order} units of this product per order."
        )
        return

    if product.inventory is not None and quantity > product.inventory:
        await message.answer(
            f"Only {product.inventory} unit(s) are currently available."
        )
        return

    await state.update_data(quantity=quantity)
    await _begin_question_flow(message, state, quantity)
