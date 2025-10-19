
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.keyboards.orders import (
    ORDER_CANCEL_ORDER_PREFIX,
    ORDER_LIST_BACK_CALLBACK,
    ORDER_LIST_PAGE_PREFIX,
    ORDER_REISSUE_PREFIX,
    ORDER_VIEW_PREFIX,
    order_details_keyboard,
    orders_list_keyboard,
)
from app.bot.keyboards.subscription import (
    SUBSCRIPTION_REFRESH_CALLBACK,
    build_subscription_keyboard,
)
from app.core.config import get_settings
from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories import RequiredChannelRepository, UserRepository
from app.services.container import membership_service
from app.services.config_service import ConfigService
from app.services.order_service import OrderService
from app.services.order_fulfillment import ensure_fulfillment
from app.services.order_notification_service import OrderNotificationService
from app.services.crypto_payment_service import (
    CryptoPaymentService,
    CryptoSyncResult,
    OXAPAY_EXTRA_KEY,
)

router = Router(name="common")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(
        "Welcome to Ben Bot!\nUse the interactive menu below to browse products, manage orders, or contact support.",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(message.from_user.id)),
    )


@router.callback_query(F.data == MainMenuCallback.ACCOUNT.value)
async def handle_account(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await _render_orders_overview(callback, session, state=state)
    await callback.answer()


@router.callback_query(F.data == ORDER_LIST_BACK_CALLBACK)
async def handle_orders_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    page = int(data.get("user_orders_page", 0))
    await _render_orders_overview(callback, session, page=page, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith(ORDER_LIST_PAGE_PREFIX))
async def handle_orders_paginate(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    raw = callback.data.removeprefix(ORDER_LIST_PAGE_PREFIX)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    await _render_orders_overview(callback, session, page=page, state=state)
    await callback.answer()


@router.callback_query(F.data.startswith(ORDER_VIEW_PREFIX))
async def handle_order_view(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(ORDER_VIEW_PREFIX)
    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await callback.answer("User profile not found.", show_alert=True)
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None or order.user_id != profile.id:
        await callback.answer("Order not found.", show_alert=True)
        return

    crypto_service = CryptoPaymentService(session)
    crypto_status = await crypto_service.refresh_order_status(order)

    notifications = OrderNotificationService(session)
    if crypto_status.updated:
        if order.status == OrderStatus.CANCELLED:
            await notifications.notify_cancelled(callback.bot, order, reason="provider_update")
        elif order.status == OrderStatus.EXPIRED:
            await notifications.notify_expired(callback.bot, order, reason="provider_update")

    previous_status = order.status
    await order_service.enforce_expiration(order)
    if order.status == OrderStatus.EXPIRED and previous_status != OrderStatus.EXPIRED:
        await notifications.notify_expired(callback.bot, order, reason="timeout_check")

    state_data = await state.get_data()
    current_page = int(state_data.get("user_orders_page", 0))
    await _safe_edit_message(
        callback.message,
        _format_order_details(order, crypto_status),
        reply_markup=order_details_keyboard(
            order,
            pay_link=crypto_status.pay_link,
            page=current_page,
        ),
    )

    if order.status == OrderStatus.PAID:
        await ensure_fulfillment(session, callback.bot, order, source="user_view")

    await callback.answer()


@router.callback_query(F.data.startswith(ORDER_CANCEL_ORDER_PREFIX))
async def handle_order_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(ORDER_CANCEL_ORDER_PREFIX)
    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await callback.answer("User profile not found.", show_alert=True)
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None or order.user_id != profile.id:
        await callback.answer("Order not found.", show_alert=True)
        return

    crypto_service = CryptoPaymentService(session)
    await crypto_service.refresh_order_status(order)
    await order_service.enforce_expiration(order)

    if order.status != OrderStatus.AWAITING_PAYMENT:
        await callback.answer("Order cannot be cancelled.", show_alert=True)
        return

    await order_service.mark_cancelled(order)
    await OrderNotificationService(session).notify_cancelled(callback.bot, order, reason="user_cancelled")
    state_data = await state.get_data()
    page = int(state_data.get("user_orders_page", 0))
    await _render_orders_overview(callback, session, page=page, state=state)
    await callback.answer("Order cancelled")


@router.callback_query(F.data.startswith(ORDER_REISSUE_PREFIX))
async def handle_order_reissue(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(ORDER_REISSUE_PREFIX)
    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await callback.answer("User profile not found.", show_alert=True)
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None or order.user_id != profile.id:
        await callback.answer("Order not found.", show_alert=True)
        return

    await session.refresh(order, attribute_names=["product"])

    if order.status not in {OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
        await callback.answer("Order is not eligible for a new invoice.", show_alert=True)
        return

    product = order.product
    if product is None or not product.is_active:
        await callback.answer("Product is not available at this time.", show_alert=True)
        return

    crypto_service = CryptoPaymentService(session)
    await crypto_service.invalidate_invoice(order, reason="reissued")

    config_service = ConfigService(session)
    invoice_timeout = await config_service.invoice_timeout_minutes()
    try:
        await order_service.reopen_for_payment(order, invoice_timeout_minutes=invoice_timeout)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(str(exc), show_alert=True)
        return

    result = await crypto_service.create_invoice_for_order(order, description=f"Order {order.public_id}")
    if result.error:
        await callback.answer(result.error, show_alert=True)
        return

    state_data = await state.get_data()
    current_page = int(state_data.get("user_orders_page", 0))

    await _safe_edit_message(
        callback.message,
        _format_order_details(order, None),
        reply_markup=order_details_keyboard(
            order,
            pay_link=result.pay_link,
            page=current_page,
        ),
    )
    await callback.answer("New invoice created.")


@router.callback_query(F.data == SUBSCRIPTION_REFRESH_CALLBACK)
async def handle_subscription_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    channel_repo = RequiredChannelRepository(session)
    channels = await channel_repo.list_active()

    is_allowed = await membership_service.user_can_access(
        bot=callback.bot,
        user_id=callback.from_user.id,
        session=session,
        channels=channels,
    )

    if is_allowed:
        membership_service.invalidate_user(callback.from_user.id)
        await callback.answer("Thanks! Access granted.")
        await _safe_edit_message(
            callback.message,
            "Welcome back! Choose an option below.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    keyboard = build_subscription_keyboard(list(channels)) if channels else None
    await callback.answer("You still need to join the required channels.", show_alert=True)
    await _safe_edit_message(
        callback.message,
        "Please join the required channel(s) before continuing.\nTap 'I've Joined' once you have access.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "subscription:no_link")
async def handle_subscription_no_link(callback: CallbackQuery) -> None:
    await callback.answer(
        "Channel link is not configured. Please contact the administrator.",
        show_alert=True,
    )


ORDERS_PAGE_SIZE = 5


async def _render_orders_overview(
    callback: CallbackQuery,
    session: AsyncSession,
    *,
    page: int = 0,
    state: FSMContext | None = None,
) -> None:
    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await _safe_edit_message(
            callback.message,
            "We could not locate your profile. Try again later.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    order_service = OrderService(session)
    offset = max(page, 0) * ORDERS_PAGE_SIZE
    orders, has_more = await order_service.paginate_user_orders(
        profile.id,
        limit=ORDERS_PAGE_SIZE,
        offset=offset,
    )
    has_prev = page > 0 and offset > 0

    if not orders and page > 0:
        # fallback to previous page if current page is empty
        page = max(page - 1, 0)
        offset = page * ORDERS_PAGE_SIZE
        orders, has_more = await order_service.paginate_user_orders(
            profile.id,
            limit=ORDERS_PAGE_SIZE,
            offset=offset,
        )
        has_prev = page > 0 and offset > 0

    if not orders:
        await _safe_edit_message(
            callback.message,
            "You have no orders yet.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    if state is not None:
        await state.update_data(user_orders_page=page)

    summary = _format_orders_overview(
        orders,
        page=page,
        page_size=ORDERS_PAGE_SIZE,
        has_prev=has_prev,
        has_more=has_more,
    )
    reply_markup = orders_list_keyboard(
        orders,
        page=page,
        page_size=ORDERS_PAGE_SIZE,
        has_prev=has_prev,
        has_next=has_more,
    )
    await _safe_edit_message(callback.message, summary, reply_markup=reply_markup)


@router.message(Command("cancel"))
async def handle_global_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Nothing to cancel.")
        return
    await state.clear()
    await message.answer("Operation cancelled.")


def _format_orders_overview(
    orders: list[Order],
    *,
    page: int,
    page_size: int,
    has_prev: bool,
    has_more: bool,
) -> str:
    lines = ["<b>Your orders</b>"]
    page_info = f"Page {page + 1}"
    if has_prev or has_more:
        hints = []
        if has_prev:
            hints.append("Prev available")
        if has_more:
            hints.append("Next available")
        if hints:
            page_info += f" ({', '.join(hints)})"
    lines.append(page_info)
    start_index = page * page_size
    for idx, order in enumerate(orders, start=start_index + 1):
        status = _order_display_status(order)
        created = order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "-"
        lines.append(f"{idx}. {status} - {order.total_amount} {order.currency} - created {created}")
    lines.append("")
    lines.append("Select an order to view details.")
    return "\n".join(lines)


def _format_order_details(order: Order, crypto_status: CryptoSyncResult | None = None) -> str:
    lines = [
        f"<b>Order {order.public_id}</b>",
        f"Status: {_order_display_status(order)}",
        f"Total: {order.total_amount} {order.currency}",
    ]
    if order.invoice_payload:
        lines.append(f"Payment reference: <code>{order.invoice_payload}</code>")
    if order.payment_expires_at:
        deadline = _ensure_utc(order.payment_expires_at)
        remaining = deadline - datetime.now(tz=timezone.utc)
        minutes = int(max(0, remaining.total_seconds()) // 60)
        lines.append(f"Payment deadline: {deadline:%Y-%m-%d %H:%M UTC}")
        if minutes > 0:
            lines.append(f"Time remaining: ~{minutes} minutes")
    if order.answers:
        lines.append("")
        lines.append("<b>Details</b>")
        for answer in order.answers:
            lines.append(f"{answer.question_key}: {answer.answer_text or '-'}")

    if order.status == OrderStatus.CANCELLED:
        lines.append("")
        lines.append("This order was cancelled. Use the button below to create a fresh invoice when you're ready.")
    elif order.status == OrderStatus.EXPIRED:
        lines.append("")
        lines.append("The invoice expired before payment. Tap the button to generate a new one.")

    oxapay = _get_oxapay_payment(order)
    pay_link = None
    if crypto_status and crypto_status.pay_link:
        pay_link = crypto_status.pay_link
    elif oxapay.get("pay_link"):
        pay_link = oxapay.get("pay_link")

    if crypto_status and crypto_status.error:
        lines.append("")
        lines.append(f"⚠️ Crypto sync issue: {crypto_status.error}")

    if oxapay or pay_link:
        lines.append("")
        lines.append("<b>Crypto payment</b>")
        status_text = None
        if crypto_status and crypto_status.status:
            status_text = crypto_status.status
        elif oxapay.get("status"):
            status_text = oxapay["status"]
        if status_text:
            lines.append(f"Status: {status_text}")
        if pay_link:
            lines.append(f'<a href="{pay_link}">Open crypto checkout</a>')
        if oxapay.get("updated_at"):
            lines.append(f"Last update: {oxapay['updated_at']}")

    fulfillment_meta = oxapay.get("fulfillment") if isinstance(oxapay, dict) else {}
    if fulfillment_meta:
        context = fulfillment_meta.get("context") or {}
        actions = fulfillment_meta.get("actions") or []
        lines.append("")
        lines.append("<b>Fulfillment</b>")
        if context.get("license_code"):
            lines.append(f"License: <code>{context['license_code']}</code>")
        if actions:
            for action in actions:
                if not isinstance(action, dict):
                    continue
                action_name = action.get("action", "?")
                status = action.get("status", "?")
                detail = action.get("detail")
                lines.append(f"{action_name}: {status}")
                if detail:
                    lines.append(f" - {detail}")

    return "\n".join(lines)


async def _safe_edit_message(message, text: str, *, reply_markup=None) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await message.answer(text, reply_markup=reply_markup)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _user_is_owner(user_id: int | None) -> bool:
    if user_id is None:
        return False
    settings = get_settings()
    return user_id in settings.owner_user_ids


def _get_oxapay_payment(order: Order) -> dict[str, Any]:
    extra = order.extra_attrs or {}
    data = extra.get(OXAPAY_EXTRA_KEY)
    if isinstance(data, dict):
        return data
    return {}


def _order_display_status(order: Order) -> str:
    base = order.status.value.replace("_", " ").title()
    if order.status == OrderStatus.PAID:
        oxapay = _get_oxapay_payment(order)
        fulfillment = oxapay.get("fulfillment") if isinstance(oxapay, dict) else {}
        delivered_at = fulfillment.get("delivered_at") if isinstance(fulfillment, dict) else None
        if delivered_at:
            return "Delivered"
    return base


