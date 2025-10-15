
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.keyboards.orders import (
    ORDER_CANCEL_ORDER_PREFIX,
    ORDER_LIST_BACK_CALLBACK,
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
async def handle_account(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_orders_overview(callback, session)
    await callback.answer()


@router.callback_query(F.data == ORDER_LIST_BACK_CALLBACK)
async def handle_orders_back(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_orders_overview(callback, session)
    await callback.answer()


@router.callback_query(F.data.startswith(ORDER_VIEW_PREFIX))
async def handle_order_view(callback: CallbackQuery, session: AsyncSession) -> None:
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

    await _safe_edit_message(
        callback.message,
        _format_order_details(order, crypto_status),
        reply_markup=order_details_keyboard(order, pay_link=crypto_status.pay_link),
    )

    if order.status == OrderStatus.PAID:
        await ensure_fulfillment(session, callback.bot, order, source="user_view")

    await callback.answer()


@router.callback_query(F.data.startswith(ORDER_CANCEL_ORDER_PREFIX))
async def handle_order_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
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
    await _render_orders_overview(callback, session)
    await callback.answer("Order cancelled")


@router.callback_query(F.data == MainMenuCallback.SUPPORT.value)
async def handle_support(callback: CallbackQuery) -> None:
    await _safe_edit_message(
        callback.message,
        "Support center is under construction. Use this menu later to raise tickets or chat with the team.",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
    )
    await callback.answer()


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


async def _render_orders_overview(callback: CallbackQuery, session: AsyncSession) -> None:
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
    orders = await order_service.list_user_orders(profile.id)

    if not orders:
        await _safe_edit_message(
            callback.message,
            "You have no orders yet.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    summary = _format_orders_overview(orders)
    reply_markup = orders_list_keyboard(orders[:10])
    await _safe_edit_message(callback.message, summary, reply_markup=reply_markup)



def _format_orders_overview(orders: list[Order]) -> str:
    lines = ["<b>Your orders</b>"]
    for order in orders[:10]:
        status = order.status.value.replace("_", " ").title()
        created = order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "-"
        lines.append(f"{status} - {order.total_amount} {order.currency} - created {created}")
    if len(orders) > 10:
        lines.append("Showing the latest 10 orders.")
    lines.append("")
    lines.append("Select an order to view details.")
    return "\n".join(lines)


def _format_order_details(order: Order, crypto_status: CryptoSyncResult | None = None) -> str:
    lines = [
        f"<b>Order {order.public_id}</b>",
        f"Status: {order.status.value.replace('_', ' ').title()}",
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


