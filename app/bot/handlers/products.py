from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
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
    PRODUCT_ALL_CALLBACK,
    PRODUCT_CATEGORY_MENU_CALLBACK,
    PRODUCT_CATEGORY_PREFIX,
    PRODUCT_LIST_BACK_CALLBACK,
    PRODUCT_ORDER_PREFIX,
    PRODUCT_VIEW_PREFIX,
    product_category_keyboard,
    product_details_keyboard,
    products_list_keyboard,
)
from app.bot.keyboards.cart import cart_checkout_confirmation_keyboard
from app.bot.states.order import OrderFlowState
from app.core.config import get_settings
from app.core.enums import OrderStatus, ProductQuestionType
from app.infrastructure.db.models import Order, Product
from app.infrastructure.db.repositories import OrderRepository, UserRepository
from app.services.cart_service import CartService
from app.services.config_service import ConfigService
from app.services.crypto_payment_service import (
    CryptoInvoiceResult,
    CryptoPaymentService,
)
from app.services.category_service import CategoryService
from app.services.loyalty_service import LoyaltyService
from app.services.loyalty_order_service import (
    ensure_points_available,
    reserve_loyalty_for_order,
)
from app.services.order_service import OrderCreationError, OrderService
from app.services.product_service import ProductService
from app.services.recommendation_service import RecommendationService


router = Router(name="products")

CURRENCY_QUANT = Decimal("0.01")


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
        "telegram_user_id": callback.from_user.id,
        "cart_checkout_index": cart_index,
        "cart_answers": cart_answers or [],
        "cart_totals": cart_totals,
        "cart_currency": cart_currency,
        "loyalty_prompt_status": None,
        "loyalty_redeem_points": None,
        "loyalty_redeem_value": None,
        "loyalty_total_due": None,
        "loyalty_mode": None,
        "loyalty_user_profile_id": None,
        "loyalty_account_id": None,
    }

    if origin != "direct" and cart_queue:
        quantity = _resolve_cart_quantity(cart_queue, cart_index)
        update_payload.update({
            "quantity": quantity,
            "question_index": 0,
            "answers": [],
        })
        await state.update_data(**update_payload)
        await _begin_question_flow(callback.message, state, session, quantity)
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
        await _begin_question_flow(
            callback.message,
            state,
            session,
            max(1, int(existing_quantity or 1)),
        )
    return True


@router.callback_query(F.data == MainMenuCallback.PRODUCTS.value)
async def handle_show_products(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    category_service = CategoryService(session)
    categories = await category_service.list_active_categories()

    if categories:
        await state.update_data(product_list_context=None)
        await _render_category_menu(callback.message, categories)
        await callback.answer()
        return

    service = ProductService(session)
    products = await service.list_active_products()
    await _set_product_list_context(
        state,
        mode="all",
        category_id=None,
        back_callback=PRODUCT_BACK_CALLBACK,
        category_name=None,
    )
    await _render_product_list(
        callback.message,
        products,
        title="Available products:",
        empty_message="No products are available yet. Please check back soon.",
        back_callback=PRODUCT_BACK_CALLBACK,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(PRODUCT_VIEW_PREFIX))
async def handle_view_product(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    product_id = int(callback.data.removeprefix(PRODUCT_VIEW_PREFIX))
    service = ProductService(session)
    product = await service.get_product(product_id)

    if product is None or not product.is_active:
        await callback.answer("Product is not available", show_alert=True)
        return

    state_data = await state.get_data()
    context = state_data.get("product_list_context") or {}
    back_callback = context.get("back_callback", PRODUCT_BACK_CALLBACK)

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
        reply_markup=product_details_keyboard(product.id, back_callback=PRODUCT_LIST_BACK_CALLBACK),
    )
    await _send_related_products(callback.message, session, product_id)
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


@router.callback_query(F.data == PRODUCT_ALL_CALLBACK)
async def handle_all_products(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    service = ProductService(session)
    products = await service.list_active_products()
    await _set_product_list_context(
        state,
        mode="all",
        category_id=None,
        back_callback=PRODUCT_CATEGORY_MENU_CALLBACK,
        category_name=None,
    )
    await _render_product_list(
        callback.message,
        products,
        title="All products:",
        empty_message="No products are available yet.",
        back_callback=PRODUCT_CATEGORY_MENU_CALLBACK,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(PRODUCT_CATEGORY_PREFIX))
async def handle_products_by_category(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    raw_category_id = callback.data.removeprefix(PRODUCT_CATEGORY_PREFIX)
    try:
        category_id = int(raw_category_id)
    except ValueError:
        await callback.answer("Unknown category.", show_alert=True)
        return

    category_service = CategoryService(session)
    category = await category_service.get_category(category_id)
    if category is None or not category.is_active:
        await callback.answer("Category is not available", show_alert=True)
        categories = await category_service.list_active_categories()
        if categories:
            await _render_category_menu(callback.message, categories)
        else:
            service = ProductService(session)
            products = await service.list_active_products()
            await _set_product_list_context(
                state,
                mode="all",
                category_id=None,
                back_callback=PRODUCT_BACK_CALLBACK,
                category_name=None,
            )
            await _render_product_list(
                callback.message,
                products,
                title="Available products:",
                empty_message="No products are available yet.",
                back_callback=PRODUCT_BACK_CALLBACK,
            )
        return

    products = await category_service.list_category_products(category_id)
    await _set_product_list_context(
        state,
        mode="category",
        category_id=category.id,
        back_callback=PRODUCT_CATEGORY_MENU_CALLBACK,
        category_name=category.name,
    )
    await _render_product_list(
        callback.message,
        products,
        title=f"{category.name}:",
        empty_message="No products are available in this category yet.",
        back_callback=PRODUCT_CATEGORY_MENU_CALLBACK,
    )
    await callback.answer()


@router.callback_query(F.data == PRODUCT_CATEGORY_MENU_CALLBACK)
async def handle_product_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    category_service = CategoryService(session)
    categories = await category_service.list_active_categories()
    if categories:
        await state.update_data(product_list_context=None)
        await _render_category_menu(callback.message, categories)
    else:
        service = ProductService(session)
        products = await service.list_active_products()
        await _set_product_list_context(
            state,
            mode="all",
            category_id=None,
            back_callback=PRODUCT_BACK_CALLBACK,
            category_name=None,
        )
        await _render_product_list(
            callback.message,
            products,
            title="Available products:",
            empty_message="No products are available yet.",
            back_callback=PRODUCT_BACK_CALLBACK,
        )
    await callback.answer()


@router.callback_query(F.data == PRODUCT_LIST_BACK_CALLBACK)
async def handle_product_list_back(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    context = data.get("product_list_context") or {}
    await _show_products_from_context(callback.message, session, state, context)
    await callback.answer()


async def _render_category_menu(message: Message, categories: list) -> None:
    await _safe_edit_message(
        message,
        "Browse products by category:",
        reply_markup=product_category_keyboard(categories),
    )


async def _set_product_list_context(
    state: FSMContext,
    *,
    mode: str,
    category_id: int | None,
    back_callback: str,
    category_name: str | None,
) -> None:
    await state.update_data(
        product_list_context={
            "mode": mode,
            "category_id": category_id,
            "back_callback": back_callback,
            "category_name": category_name,
        }
    )


async def _render_product_list(
    message: Message,
    products: list[Product],
    *,
    title: str,
    empty_message: str,
    back_callback: str,
) -> None:
    if not products:
        await _safe_edit_message(
            message,
            empty_message,
            reply_markup=products_list_keyboard([], back_callback=back_callback),
        )
        return
    await _safe_edit_message(
        message,
        title,
        reply_markup=products_list_keyboard(products, back_callback=back_callback),
    )


async def _show_products_from_context(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    context: dict,
) -> None:
    mode = context.get("mode")
    back_callback = context.get("back_callback", PRODUCT_BACK_CALLBACK)

    if mode == "category":
        category_id = context.get("category_id")
        category_service = CategoryService(session)
        if category_id is None:
            categories = await category_service.list_active_categories()
            if categories:
                await state.update_data(product_list_context=None)
                await _render_category_menu(message, categories)
            else:
                service = ProductService(session)
                products = await service.list_active_products()
                await _set_product_list_context(
                    state,
                    mode="all",
                    category_id=None,
                    back_callback=PRODUCT_BACK_CALLBACK,
                    category_name=None,
                )
                await _render_product_list(
                    message,
                    products,
                    title="Available products:",
                    empty_message="No products are available yet.",
                    back_callback=PRODUCT_BACK_CALLBACK,
                )
            return

        category = await category_service.get_category(category_id)
        if category is None or not category.is_active:
            categories = await category_service.list_active_categories()
            if categories:
                await state.update_data(product_list_context=None)
                await _render_category_menu(message, categories)
            else:
                service = ProductService(session)
                products = await service.list_active_products()
                await _set_product_list_context(
                    state,
                    mode="all",
                    category_id=None,
                    back_callback=PRODUCT_BACK_CALLBACK,
                    category_name=None,
                )
                await _render_product_list(
                    message,
                    products,
                    title="Available products:",
                    empty_message="No products are available yet.",
                    back_callback=PRODUCT_BACK_CALLBACK,
                )
            return

        products = await category_service.list_category_products(category.id)
        await _set_product_list_context(
            state,
            mode="category",
            category_id=category.id,
            back_callback=back_callback,
            category_name=category.name,
        )
        await _render_product_list(
            message,
            products,
            title=f"{category.name}:",
            empty_message="No products are available in this category yet.",
            back_callback=back_callback,
        )
        return

    service = ProductService(session)
    products = await service.list_active_products()
    await _set_product_list_context(
        state,
        mode="all",
        category_id=None,
        back_callback=back_callback,
        category_name=None,
    )
    await _render_product_list(
        message,
        products,
        title="All products:",
        empty_message="No products are available yet.",
        back_callback=back_callback,
    )


async def _send_related_products(message: Message, session: AsyncSession, product_id: int) -> None:
    recommendation_service = RecommendationService(session)
    try:
        related = await recommendation_service.get_related_products(product_id, limit=3)
    except Exception:  # noqa: BLE001
        return

    related = [item for item in related if item.id != product_id and item.is_active]
    if not related:
        return

    builder = InlineKeyboardBuilder()
    for product in related:
        builder.button(
            text=f"{product.name} - {product.price} {product.currency}",
            callback_data=f"{PRODUCT_VIEW_PREFIX}{product.id}",
        )
    builder.button(text="Back", callback_data=PRODUCT_LIST_BACK_CALLBACK)
    builder.adjust(1)
    await message.answer("You might also like:", reply_markup=builder.as_markup())


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
async def collect_order_answer(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await _cancel_order_flow(message, state, "Order cancelled.")
        return

    data = await state.get_data()
    questions: List[dict[str, Any]] = data.get("questions", [])
    index: int = data.get("question_index", 0)

    if index >= len(questions):
        await _complete_question_flow(message, state, session)
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
        await _complete_question_flow(message, state, session)
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
        if callback.message:
            await state.update_data(
                cart_summary_message_chat=callback.message.chat.id,
                cart_summary_message_id=callback.message.message_id,
            )
        prompted = await _maybe_prompt_loyalty(
            callback.message,
            state,
            session,
            mode="cart",
        )
        if prompted:
            await callback.answer("Choose how many loyalty points to redeem, then continue.")
            return

        summary_text = _format_cart_summary_for_confirmation(cart_queue, totals, currency)
        await state.set_state(OrderFlowState.cart_confirm)
        await _render_cart_summary_from_state(
            state,
            callback.bot,
            summary_text,
            reply_markup=cart_checkout_confirmation_keyboard(),
            fallback_chat_id=callback.message.chat.id if callback.message else callback.from_user.id,
        )
        await callback.answer("Review your cart and confirm.")
        return

    # Answer immediately to avoid Telegram timeout while we process payment setup.
    await callback.answer("Processing order...", cache_time=0)

    base_price = Decimal(str(product.price)).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    base_total = (base_price * quantity).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    loyalty_points = int(data.get("loyalty_redeem_points") or 0)
    loyalty_value = Decimal(str(data.get("loyalty_redeem_value") or "0")).quantize(
        CURRENCY_QUANT,
        rounding=ROUND_HALF_UP,
    )
    ratio = Decimal(str(data.get("loyalty_ratio") or "0")) if loyalty_points else Decimal("0")
    total_due = Decimal(str(data.get("loyalty_total_due") or base_total)).quantize(
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
            total_due = base_total
    if loyalty_points == 0 or loyalty_value <= Decimal("0"):
        loyalty_points = 0
        loyalty_value = Decimal("0")
        total_due = base_total
    else:
        total_due = max(Decimal("0"), min(total_due, base_total))
        if ratio <= Decimal("0"):
            ratio = (loyalty_value / Decimal(loyalty_points)).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)

    loyalty_meta: dict[str, Any] | None = None
    if loyalty_points > 0 and loyalty_value > Decimal("0"):
        loyalty_meta = {
            "redeem": {
                "points": loyalty_points,
                "value": str(loyalty_value),
                "ratio": str(ratio),
                "currency": product.currency,
                "status": "pending",
            }
        }

    order_kwargs: dict[str, Any] = {
        "user_id": profile.id,
        "product": product,
        "answers": answer_pairs,
        "invoice_timeout_minutes": timeout_minutes,
        "extra_attrs": {"quantity": quantity},
    }
    if loyalty_meta:
        order_kwargs["extra_attrs"]["loyalty"] = loyalty_meta
    order_kwargs["total_override"] = total_due

    try:
        order = await order_service.create_order(**order_kwargs)
    except OrderCreationError as exc:
        await state.clear()
        await callback.answer(str(exc), show_alert=True)
        return

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
                currency=order.currency,
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
                    "currency": order.currency,
                    "status": "failed",
                }
            )
            await OrderRepository(session).merge_extra_attrs(order, {"loyalty": loyalty_meta_reserved})
            order.extra_attrs = order.extra_attrs or {}
            order.extra_attrs["loyalty"] = loyalty_meta_reserved

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
    if loyalty_points > 0 and loyalty_value > Decimal("0"):
        display_answers.append(
            {
                "key": "loyalty_discount",
                "prompt": "Loyalty discount",
                "value": f"{loyalty_value} {order.currency} ({loyalty_points} pts)",
            }
        )

    await _safe_edit_message(
        callback.message,
        _order_confirmation_message(order, product_name, display_answers, crypto_result, quantity=quantity),
        reply_markup=_order_confirmation_keyboard(crypto_result),
    )
    await callback.message.answer("Order created. Check the message above for payment details.")
    if loyalty_warning:
        await callback.message.answer(
            "Loyalty points could not be applied because your available balance changed. No points were deducted."
        )

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
    currency = data.get("currency") or get_settings().payment_currency
    quantity = max(1, int(data.get("quantity", 1) or 1))
    try:
        unit_price = Decimal(str(price or "0")).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001
        unit_price = Decimal("0.00")
    subtotal = (unit_price * quantity).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    discount = Decimal(str(data.get("loyalty_redeem_value") or "0")).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    discount = min(discount, subtotal)
    total_due = (subtotal - discount).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    answers: List[dict[str, str | None]] = list(data.get("answers", []))

    lines = [
        f"<b>{product_name}</b>",
        f"Unit price: {unit_price} {currency}",
    ]
    if quantity > 1:
        lines.append(f"Quantity: {quantity}")
        lines.append(f"Subtotal: {subtotal} {currency}")
    if discount > Decimal("0"):
        lines.append(f"Loyalty discount: -{discount} {currency}")
    lines.append(f"Total due: {total_due} {currency}")
    lines.append("")
    lines.append("<b>Order details</b>")

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
    loyalty_meta = (order.extra_attrs or {}).get("loyalty") if isinstance(order.extra_attrs, dict) else {}
    if isinstance(loyalty_meta, dict):
        redeem_meta = loyalty_meta.get("redeem")
        if isinstance(redeem_meta, dict):
            value_raw = redeem_meta.get("value")
            points = redeem_meta.get("points")
            status = (redeem_meta.get("status") or "").lower()
            try:
                value_decimal = Decimal(str(value_raw))
            except Exception:  # noqa: BLE001
                value_decimal = Decimal("0")
            if value_decimal > Decimal("0"):
                lines.append("")
                label = f"Loyalty discount: -{value_raw} {order.currency}"
                if points:
                    label = f"{label} ({points} pts)"
                if status in {"reserved", "pending"}:
                    label = f"{label} [reserved]"
                elif status == "applied":
                    label = f"{label} [applied]"
                elif status == "refunded":
                    label = f"{label} [refunded]"
                lines.append(label)
            elif status == "failed":
                lines.append("")
                lines.append("Loyalty discount could not be applied. Your points remain available.")
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


async def _begin_question_flow(
    target_message: Message,
    state: FSMContext,
    session: AsyncSession,
    quantity: int,
) -> None:
    quantity = max(1, quantity)
    await state.update_data(quantity=quantity, question_index=0, answers=[])
    data = await state.get_data()
    questions: List[dict[str, Any]] = data.get("questions", [])
    if questions:
        await state.set_state(OrderFlowState.collecting_answer)
        await _prompt_question(target_message, questions[0], quantity=quantity)
        return

    origin = data.get("origin", "direct")
    if origin == "direct":
        prompted = await _maybe_prompt_loyalty(
            target_message,
            state,
            session,
            mode="direct",
        )
        if prompted:
            return
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


async def _render_cart_summary_from_state(
    state: FSMContext,
    bot,
    text: str,
    *,
    reply_markup,
    fallback_chat_id: int,
) -> None:
    data = await state.get_data()
    chat_id = data.get("cart_summary_message_chat")
    message_id = data.get("cart_summary_message_id")
    if chat_id and message_id:
        try:
            await bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
            return
        except TelegramBadRequest:
            pass

    sent = await bot.send_message(
        fallback_chat_id,
        text,
        reply_markup=reply_markup,
    )
    await state.update_data(
        cart_summary_message_chat=sent.chat.id,
        cart_summary_message_id=sent.message_id,
    )


async def _complete_question_flow(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    origin = data.get("origin", "direct")
    if origin == "direct":
        prompted = await _maybe_prompt_loyalty(
            message,
            state,
            session,
            mode="direct",
        )
        if prompted:
            return
    await _show_order_confirmation(message, state)
    await state.set_state(OrderFlowState.confirm)


async def _maybe_prompt_loyalty(
    message: Message | None,
    state: FSMContext,
    session: AsyncSession,
    *,
    mode: str,
) -> bool:
    data = await state.get_data()
    if data.get("loyalty_prompt_status") == "pending":
        return True
    if data.get("loyalty_prompt_status") == "complete":
        return False

    config_service = ConfigService(session)
    loyalty_settings = await config_service.get_loyalty_settings()
    if not loyalty_settings.enabled or loyalty_settings.redeem_ratio <= 0:
        return False
    if not loyalty_settings.auto_prompt:
        return False

    telegram_id = data.get("telegram_user_id")
    if telegram_id is None and message is not None and getattr(message, "chat", None):
        telegram_id = getattr(message.chat, "id", None)
    if telegram_id is None:
        return False

    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(telegram_id)
    if profile is None:
        return False

    loyalty_service = LoyaltyService(session)
    account = await loyalty_service.get_or_create_account(profile.id)
    balance = account.balance or Decimal("0")
    available_points = int(max(balance.to_integral_value(rounding=ROUND_DOWN), 0))
    if available_points <= 0:
        return False

    ratio = Decimal(str(loyalty_settings.redeem_ratio))
    if ratio <= Decimal("0"):
        return False

    currency: str
    base_amount: Decimal
    if mode == "direct":
        try:
            price = Decimal(str(data.get("price") or "0"))
        except Exception:  # noqa: BLE001
            return False
        quantity = max(1, int(data.get("quantity", 1) or 1))
        base_amount = (price * quantity).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
        currency = data.get("currency") or get_settings().payment_currency
    elif mode == "cart":
        totals_base = data.get("cart_totals_base") or {}
        total_raw = totals_base.get("total") or totals_base.get("total_before_loyalty") or "0"
        try:
            base_amount = Decimal(str(total_raw)).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
        except Exception:  # noqa: BLE001
            return False
        currency = data.get("cart_currency") or get_settings().payment_currency
    else:
        return False

    if base_amount <= Decimal("0"):
        return False

    max_by_amount = int((base_amount / ratio).to_integral_value(rounding=ROUND_DOWN))
    max_points = min(available_points, max_by_amount)
    if max_points <= 0 or max_points < loyalty_settings.min_redeem_points:
        return False

    prompt_text = _format_loyalty_prompt_text(
        balance_points=available_points,
        max_points=max_points,
        min_points=loyalty_settings.min_redeem_points,
        ratio=ratio,
        currency=currency,
        base_amount=base_amount,
    )

    await state.update_data(
        loyalty_prompt_status="pending",
        loyalty_mode=mode,
        loyalty_user_profile_id=profile.id,
        loyalty_account_id=account.id,
        loyalty_balance_points=str(available_points),
        loyalty_max_points=max_points,
        loyalty_min_points=loyalty_settings.min_redeem_points,
        loyalty_ratio=str(ratio),
        loyalty_currency=currency,
        loyalty_base_amount=str(base_amount),
    )

    if message is None:
        return False

    await state.set_state(OrderFlowState.loyalty)
    await message.answer(prompt_text)
    return True


def _format_loyalty_prompt_text(
    *,
    balance_points: int,
    max_points: int,
    min_points: int,
    ratio: Decimal,
    currency: str,
    base_amount: Decimal,
) -> str:
    balance_value = (Decimal(balance_points) * ratio).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    max_value = (Decimal(max_points) * ratio).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    lines = [
        "<b>Loyalty rewards</b>",
        f"Available balance: {balance_points} pts (~{balance_value} {currency}).",
        f"Order total: {base_amount} {currency}.",
        f"Maximum redeemable now: {max_points} pts (~{max_value} {currency}).",
    ]
    if min_points > 0:
        lines.append(f"Minimum redemption: {min_points} pts.")
    lines.append("Send the number of points to redeem, 'max' to use the maximum, or /skip to continue without redeeming.")
    lines.append("Send /cancel to abort.")
    return "\n".join(lines)


@router.message(OrderFlowState.loyalty)
async def collect_loyalty_choice(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if text.lower() == "/cancel":
        await _cancel_order_flow(message, state, "Order cancelled.")
        return

    data = await state.get_data()
    mode = data.get("loyalty_mode", "direct")
    max_points = int(data.get("loyalty_max_points", 0) or 0)
    min_points = int(data.get("loyalty_min_points", 0) or 0)
    ratio = Decimal(str(data.get("loyalty_ratio") or "0"))
    currency = data.get("loyalty_currency") or data.get("currency") or get_settings().payment_currency
    try:
        base_amount = Decimal(str(data.get("loyalty_base_amount") or "0")).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001
        base_amount = Decimal("0")

    if ratio <= Decimal("0") or base_amount <= Decimal("0") or max_points <= 0:
        await state.update_data(
            loyalty_prompt_status="complete",
            loyalty_redeem_points=0,
            loyalty_redeem_value="0",
            loyalty_total_due=str(base_amount),
        )
        if mode == "cart":
            await _render_cart_summary_after_loyalty(message, state)
        else:
            await _show_order_confirmation(message, state)
            await state.set_state(OrderFlowState.confirm)
        return

    if text.lower() in {"", "/skip", "skip"}:
        points = 0
    elif text.lower() in {"max", "all"}:
        points = max_points
    elif text.isdigit():
        points = int(text)
    else:
        await message.answer("Enter the number of points to redeem, 'max', or /skip to continue without redeeming.")
        return

    if points < 0:
        await message.answer("Points cannot be negative.")
        return
    if points > max_points:
        await message.answer(f"You can redeem up to {max_points} points on this order.")
        return
    if points != 0 and points < min_points:
        await message.answer(f"Redeem at least {min_points} points or send /skip to continue without applying points.")
        return

    discount = (Decimal(points) * ratio).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    if discount >= base_amount:
        discount = base_amount
        adjusted_points = int((discount / ratio).to_integral_value(rounding=ROUND_DOWN))
        points = min(adjusted_points, max_points)
    total_due = (base_amount - discount).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)

    await state.update_data(
        loyalty_prompt_status="complete",
        loyalty_redeem_points=points,
        loyalty_redeem_value=str(discount),
        loyalty_total_due=str(total_due),
    )

    if mode == "cart":
        await _render_cart_summary_after_loyalty(message, state)
    else:
        await _show_order_confirmation(message, state)
        await state.set_state(OrderFlowState.confirm)


async def _render_cart_summary_after_loyalty(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    cart_queue = data.get("cart_checkout_queue") or []
    totals_base = data.get("cart_totals_base") or {}
    totals = dict(data.get("cart_totals") or {})
    currency = data.get("cart_currency") or get_settings().payment_currency
    redeem_value = Decimal(str(data.get("loyalty_redeem_value") or "0")).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
    total_due = Decimal(str(data.get("loyalty_total_due") or totals_base.get("total", "0") or "0")).quantize(
        CURRENCY_QUANT,
        rounding=ROUND_HALF_UP,
    )

    totals["loyalty_discount"] = str(redeem_value)
    totals["total"] = str(total_due)

    await state.update_data(cart_totals=totals)
    summary_text = _format_cart_summary_for_confirmation(cart_queue, totals, currency)
    await state.set_state(OrderFlowState.cart_confirm)
    await _render_cart_summary_from_state(
        state,
        message.bot,
        summary_text,
        reply_markup=cart_checkout_confirmation_keyboard(),
        fallback_chat_id=message.chat.id,
    )
def _extract_email_from_answers(answers: list[dict[str, str | None]]) -> str | None:
    for item in answers:
        raw = (item.get("value") or "").strip()
        if not raw:
            continue

        candidates: list[str] = []
        if item.get("type") == ProductQuestionType.EMAIL.value:
            candidates = [seg.strip() for seg in re.split(r"[\n,]+", raw) if seg.strip()]
        else:
            key = (item.get("key") or "").lower()
            prompt = (item.get("prompt") or "").lower()
            if "email" in key or "email" in prompt:
                candidates = [seg.strip() for seg in re.split(r"[\n,]+", raw) if seg.strip()]
            elif re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", raw):
                candidates = [raw]

        for candidate in candidates:
            if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", candidate):
                return candidate
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
    await _begin_question_flow(message, state, session, quantity)
