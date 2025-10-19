from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin import _format_admin_order_detail
from app.bot.keyboards.admin import AdminMenuCallback, order_manage_keyboard
from app.bot.keyboards.admin_payments import (
    AdminPaymentsCallback,
    ADMIN_PAYMENTS_PENDING_PAGE_PREFIX,
    ADMIN_PAYMENTS_RECENT_PAGE_PREFIX,
    payments_dashboard_keyboard,
    payments_orders_keyboard,
)
from app.bot.states.admin_payments import AdminPaymentsState
from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories.order import OrderRepository
from app.services.crypto_payment_service import CryptoPaymentService, OXAPAY_EXTRA_KEY
from app.services.order_fulfillment import ensure_fulfillment
from app.services.order_notification_service import OrderNotificationService
from app.services.order_service import OrderService

router = Router(name="admin_payments")

PENDING_PAGE_SIZE = 5
RECENT_PAGE_SIZE = 5


@router.callback_query(F.data == AdminMenuCallback.MANAGE_PAYMENTS.value)
async def handle_admin_payments_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_payments_dashboard(callback.message, session)
    await callback.answer()


@router.callback_query(F.data == AdminPaymentsCallback.REFRESH.value)
async def handle_admin_payments_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_payments_dashboard(callback.message, session, notice="Dashboard refreshed.")
    await callback.answer()


@router.callback_query(F.data == AdminPaymentsCallback.SEARCH_ORDER.value)
async def handle_admin_payments_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminPaymentsState.searching)
    await state.update_data(
        dashboard_chat_id=callback.message.chat.id,
        dashboard_message_id=callback.message.message_id,
    )
    await callback.message.answer("Enter the order public ID. Send /cancel to abort.")
    await callback.answer()


@router.callback_query(F.data == AdminPaymentsCallback.VIEW_PENDING.value)
async def handle_admin_payments_pending(callback: CallbackQuery, session: AsyncSession) -> None:
    rendered = await _render_pending_orders_list(callback.message, session, page=0)
    if not rendered:
        await callback.answer("No pending invoices.", show_alert=True)
        await _render_payments_dashboard(callback.message, session, notice="No pending invoices to display.")
        return
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_PAYMENTS_PENDING_PAGE_PREFIX))
async def handle_admin_payments_pending_page(callback: CallbackQuery, session: AsyncSession) -> None:
    raw = callback.data.removeprefix(ADMIN_PAYMENTS_PENDING_PAGE_PREFIX)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    rendered = await _render_pending_orders_list(callback.message, session, page=page)
    if not rendered:
        await callback.answer("No pending invoices.", show_alert=True)
        await _render_payments_dashboard(callback.message, session, notice="No pending invoices to display.")
        return
    await callback.answer()


@router.callback_query(F.data == AdminPaymentsCallback.VIEW_RECENT_PAID.value)
async def handle_admin_payments_recent(callback: CallbackQuery, session: AsyncSession) -> None:
    rendered = await _render_recent_paid_list(callback.message, session, page=0)
    if not rendered:
        await callback.answer("No paid orders yet.", show_alert=True)
        await _render_payments_dashboard(callback.message, session, notice="No paid orders recorded yet.")
        return
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_PAYMENTS_RECENT_PAGE_PREFIX))
async def handle_admin_payments_recent_page(callback: CallbackQuery, session: AsyncSession) -> None:
    raw = callback.data.removeprefix(ADMIN_PAYMENTS_RECENT_PAGE_PREFIX)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    rendered = await _render_recent_paid_list(callback.message, session, page=page)
    if not rendered:
        await callback.answer("No paid orders yet.", show_alert=True)
        await _render_payments_dashboard(callback.message, session, notice="No paid orders recorded yet.")
        return
    await callback.answer()


@router.callback_query(F.data == AdminPaymentsCallback.SYNC_PENDING.value)
async def handle_admin_payments_sync(callback: CallbackQuery, session: AsyncSession) -> None:
    repo = OrderRepository(session)
    pending_orders = await repo.list_pending_crypto(limit=15)
    if not pending_orders:
        await callback.answer("No invoices pending sync.", show_alert=True)
        await _render_payments_dashboard(callback.message, session, notice="No pending invoices to sync.")
        return

    crypto_service = CryptoPaymentService(session)
    notifications = OrderNotificationService(session)
    order_service = OrderService(session)

    updated = 0
    fulfilled = 0
    errors = 0

    for order in pending_orders:
        previous_status = order.status
        try:
            result = await crypto_service.refresh_order_status(order)
        except Exception:
            errors += 1
            continue

        if result.updated:
            updated += 1
            if order.status == OrderStatus.PAID:
                await ensure_fulfillment(session, callback.bot, order, source="admin_payments_sync")
                fulfilled += 1
            elif order.status == OrderStatus.CANCELLED:
                await notifications.notify_cancelled(callback.bot, order, reason="provider_update")
            elif order.status == OrderStatus.EXPIRED:
                await notifications.notify_expired(callback.bot, order, reason="provider_update")

        prev_status = order.status
        await order_service.enforce_expiration(order)
        if order.status == OrderStatus.EXPIRED and prev_status != OrderStatus.EXPIRED:
            await notifications.notify_expired(callback.bot, order, reason="timeout_check")

    notice_parts = [f"Sync complete. Checked {len(pending_orders)} invoice(s)."]
    if updated:
        notice_parts.append(f"Updated: {updated}")
    if fulfilled:
        notice_parts.append(f"Fulfilled: {fulfilled}")
    if errors:
        notice_parts.append(f"Errors: {errors}")

    await _render_payments_dashboard(callback.message, session, notice=" ".join(notice_parts))
    await callback.answer("Sync finished.")


@router.message(AdminPaymentsState.searching)
async def handle_admin_payments_search_input(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Provide an order public ID or /cancel.")
        return

    if text.lower() in {"/cancel", "cancel"}:
        await state.clear()
        await message.answer("Order search cancelled.")
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(text)
    if order is None:
        await message.answer("Order not found. Try again or send /cancel to abort.")
        return

    await state.clear()
    details = _format_admin_order_detail(order)
    markup = order_manage_keyboard(order)
    await message.answer(details, reply_markup=markup, disable_web_page_preview=True)


async def _render_payments_dashboard(message, session: AsyncSession, *, notice: str | None = None) -> None:
    repo = OrderRepository(session)
    summary = await repo.payment_status_summary()
    top_products = await repo.top_paid_products(limit=5)
    recent_paid = await repo.list_recent_paid(limit=3)

    text = _format_payments_summary(summary, top_products, recent_paid)
    if notice:
        text = f"{notice}\n\n{text}"
    markup = payments_dashboard_keyboard()
    try:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def _render_pending_orders_list(
    message,
    session: AsyncSession,
    *,
    page: int,
) -> bool:
    repo = OrderRepository(session)
    offset = max(page, 0) * PENDING_PAGE_SIZE
    orders, has_more = await repo.paginate_pending_payments(limit=PENDING_PAGE_SIZE, offset=offset)
    has_prev = page > 0 and offset > 0

    if not orders and page > 0:
        page = max(page - 1, 0)
        offset = page * PENDING_PAGE_SIZE
        orders, has_more = await repo.paginate_pending_payments(limit=PENDING_PAGE_SIZE, offset=offset)
        has_prev = page > 0 and offset > 0

    if not orders:
        return False

    text = _format_pending_orders(
        orders,
        page=page,
        page_size=PENDING_PAGE_SIZE,
        has_prev=has_prev,
        has_next=has_more,
    )
    markup = payments_orders_keyboard(
        orders,
        page=page,
        has_prev=has_prev,
        has_next=has_more,
        source_prefix=ADMIN_PAYMENTS_PENDING_PAGE_PREFIX,
        back_callback=AdminPaymentsCallback.REFRESH.value,
    )
    try:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    return True


async def _render_recent_paid_list(
    message,
    session: AsyncSession,
    *,
    page: int,
) -> bool:
    repo = OrderRepository(session)
    offset = max(page, 0) * RECENT_PAGE_SIZE
    orders, has_more = await repo.paginate_recent_paid(limit=RECENT_PAGE_SIZE, offset=offset)
    has_prev = page > 0 and offset > 0

    if not orders and page > 0:
        page = max(page - 1, 0)
        offset = page * RECENT_PAGE_SIZE
        orders, has_more = await repo.paginate_recent_paid(limit=RECENT_PAGE_SIZE, offset=offset)
        has_prev = page > 0 and offset > 0

    if not orders:
        return False

    text = _format_recent_paid_orders(
        orders,
        page=page,
        page_size=RECENT_PAGE_SIZE,
        has_prev=has_prev,
        has_next=has_more,
    )
    markup = payments_orders_keyboard(
        orders,
        page=page,
        has_prev=has_prev,
        has_next=has_more,
        source_prefix=ADMIN_PAYMENTS_RECENT_PAGE_PREFIX,
        back_callback=AdminPaymentsCallback.REFRESH.value,
    )
    try:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    return True


def _format_payments_summary(
    summary: dict[OrderStatus, dict[str, dict[str, Decimal | int]]],
    top_products: list[tuple[str, str, int, Decimal]],
    recent_paid: list[Order],
) -> str:
    lines = ["<b>Payments overview</b>"]

    total_orders = sum(int(data["count"]) for status_map in summary.values() for data in status_map.values())
    lines.append(f"Total tracked orders: {total_orders}")

    paid_info = _status_info(summary, OrderStatus.PAID)
    awaiting_info = _status_info(summary, OrderStatus.AWAITING_PAYMENT)
    cancelled_info = _status_info(summary, OrderStatus.CANCELLED)
    expired_info = _status_info(summary, OrderStatus.EXPIRED)

    if paid_info:
        lines.append(f"Paid: {paid_info}")
    if awaiting_info:
        lines.append(f"Awaiting payment: {awaiting_info}")
    if cancelled_info:
        lines.append(f"Cancelled: {cancelled_info}")
    if expired_info:
        lines.append(f"Expired: {expired_info}")

    if awaiting_info:
        lines.append("")
        lines.append(f"Outstanding revenue: {awaiting_info}")

    if top_products:
        lines.append("")
        lines.append("<b>Top products (paid)</b>")
        product_map: dict[str, list[tuple[str, int, Decimal]]] = defaultdict(list)
        for name, currency, count, total in top_products:
            product_map[name].append((currency, count, total))
        for name, entries in product_map.items():
            total_count = sum(item[1] for item in entries)
            amounts = ", ".join(f"{_format_amount(total)} {currency}" for currency, _, total in entries)
            lines.append(f"{name}: {total_count} order(s) • {amounts}")

    if recent_paid:
        lines.append("")
        lines.append("<b>Recent paid orders</b>")
        for order in recent_paid:
            timestamp = _format_datetime(order.updated_at or order.created_at)
            product_name = getattr(order.product, "name", "-")
            if order.user is not None:
                user_display = f"{order.user.display_name()} (id={order.user_id})"
            else:
                user_display = f"user_id={order.user_id}"
            lines.append(f"{_format_amount(order.total_amount)} {order.currency} • {product_name}")
            lines.append(f"{timestamp} • {user_display}")

    lines.append("")
    lines.append("Use the buttons below to drill into payments or sync invoices.")
    return "\n".join(lines)


def _format_pending_orders(
    orders: list[Order],
    *,
    page: int,
    page_size: int,
    has_prev: bool,
    has_next: bool,
) -> str:
    lines = ["<b>Pending invoices</b>"]
    page_info = f"Page {page + 1}"
    hints = []
    if has_prev:
        hints.append("Prev available")
    if has_next:
        hints.append("Next available")
    if hints:
        page_info += f" ({', '.join(hints)})"
    lines.append(page_info)
    start_index = page * page_size
    for idx, order in enumerate(orders, start=start_index + 1):
        product_name = getattr(order.product, "name", "-")
        amount = f"{_format_amount(order.total_amount)} {order.currency}"
        expires = _format_datetime(order.payment_expires_at)
        pay_link = _extract_pay_link(order)
        lines.append(f"{idx}. {product_name} • {amount}")
        lines.append(f"Order: <code>{order.public_id}</code> • User: {order.user_id}")
        if order.invoice_payload:
            lines.append(f"Track ID: {order.invoice_payload}")
        if expires:
            lines.append(f"Expires: {expires}")
        if pay_link:
            lines.append(f"Link: {pay_link}")
        lines.append("")
    lines.append("Select an order below to manage it.")
    return "\n".join(lines).rstrip()


def _format_recent_paid_orders(
    orders: list[Order],
    *,
    page: int,
    page_size: int,
    has_prev: bool,
    has_next: bool,
) -> str:
    lines = ["<b>Recently paid orders</b>"]
    page_info = f"Page {page + 1}"
    hints = []
    if has_prev:
        hints.append("Prev available")
    if has_next:
        hints.append("Next available")
    if hints:
        page_info += f" ({', '.join(hints)})"
    lines.append(page_info)
    start_index = page * page_size
    for idx, order in enumerate(orders, start=start_index + 1):
        product_name = getattr(order.product, "name", "-")
        amount = f"{_format_amount(order.total_amount)} {order.currency}"
        paid_at = _format_datetime(order.updated_at or order.created_at)
        if order.user is not None:
            user_display = f"{order.user.display_name()} (id={order.user_id})"
        else:
            user_display = f"user_id={order.user_id}"
        lines.append(f"{idx}. {product_name} • {amount}")
        lines.append(f"{paid_at} • {user_display}")
        lines.append(f"Order: <code>{order.public_id}</code>")
        lines.append("")
    lines.append("Select an order to view full details or manage fulfillment.")
    return "\n".join(lines).rstrip()


def _status_info(summary: dict[OrderStatus, dict[str, dict[str, Decimal | int]]], status: OrderStatus) -> str | None:
    entries = summary.get(status)
    if not entries:
        return None
    total_count = sum(int(value["count"]) for value in entries.values())
    parts = []
    for currency, data in entries.items():
        parts.append(f"{_format_amount(data['total'])} {currency}")
    amounts = ", ".join(parts)
    return f"{total_count} order(s){f' • {amounts}' if amounts else ''}"


def _format_amount(value: Decimal | int | float) -> str:
    if isinstance(value, Decimal):
        quantized = value.quantize(Decimal("0.01"))
        text = format(quantized, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
    return str(value)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return value.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _extract_pay_link(order: Order) -> str | None:
    extra = order.extra_attrs or {}
    meta = extra.get(OXAPAY_EXTRA_KEY)
    if isinstance(meta, dict):
        link = meta.get("pay_link")
        if isinstance(link, str):
            return link
    return None
