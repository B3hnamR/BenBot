from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    AdminCryptoCallback,
    AdminMenuCallback,
    AdminOrderCallback,
    AdminLoyaltyCallback,
    ADMIN_ORDER_MARK_FULFILLED_PREFIX,
    ADMIN_ORDER_NOTIFY_DELIVERED_PREFIX,
    ADMIN_ORDER_MARK_PAID_PREFIX,
    ADMIN_RECENT_ORDERS_PAGE_PREFIX,
    ADMIN_ORDER_RECEIPT_PREFIX,
    ADMIN_ORDER_VIEW_PREFIX,
    ADMIN_ORDER_TIMELINE_MENU_PREFIX,
    ADMIN_ORDER_TIMELINE_STATUS_PREFIX,
    ADMIN_ORDER_TIMELINE_NOTE_PREFIX,
    admin_menu_keyboard,
    crypto_settings_keyboard,
    order_manage_keyboard,
    order_settings_keyboard,
    recent_orders_keyboard,
    order_timeline_menu_keyboard,
    loyalty_settings_keyboard,
)
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.states.admin_crypto import AdminCryptoState
from app.bot.states.admin_loyalty import AdminLoyaltyState
from app.bot.states.admin_order import AdminOrderTimelineState
from app.core.config import get_settings
from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order, OrderTimeline
from app.infrastructure.db.repositories.order import OrderRepository
from app.services.config_service import ConfigService
from app.services.crypto_payment_service import CryptoPaymentService, OXAPAY_EXTRA_KEY
from app.services.order_fulfillment import ensure_fulfillment
from app.services.coupon_order_service import release_coupon_for_order
from app.services.referral_order_service import cancel_referral_for_order
from app.services.order_notification_service import OrderNotificationService
from app.services.loyalty_order_service import refund_loyalty_for_order
from app.services.order_service import OrderService
from app.services.order_summary import build_order_summary
from app.services.order_timeline_service import OrderTimelineService

router = Router(name="admin")

RECENT_ORDERS_PAGE_SIZE = 10

LEGACY_ADMIN_ORDER_TIMELINE_MENU_PREFIX = "admin:orders:timeline_menu:"
LEGACY_ADMIN_ORDER_TIMELINE_STATUS_PREFIX = "admin:orders:timeline_status:"
LEGACY_ADMIN_ORDER_TIMELINE_NOTE_PREFIX = "admin:orders:timeline_note:"


@router.callback_query(F.data == MainMenuCallback.ADMIN.value)
async def handle_admin_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    enabled = await config_service.subscription_required()

    await callback.message.edit_text(
        "Admin control panel: manage subscription gates, channels, products, and orders.",
        reply_markup=admin_menu_keyboard(subscription_enabled=enabled),
    )
    await callback.answer()


@router.callback_query(F.data == AdminMenuCallback.MANAGE_ORDERS.value)
async def handle_manage_orders(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    alerts = await config_service.get_alert_settings()
    await callback.message.edit_text(
        _format_order_alerts_text(alerts),
        reply_markup=order_settings_keyboard(alerts),
    )
    await callback.answer()


@router.callback_query(F.data == AdminMenuCallback.MANAGE_LOYALTY.value)
async def handle_manage_loyalty(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await _render_loyalty_settings_message(callback.message, session, state)
    await callback.answer()


@router.callback_query(F.data == AdminLoyaltyCallback.TOGGLE_ENABLED.value)
async def handle_loyalty_toggle_enabled(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    current = await config_service.get_loyalty_settings()
    updated = await config_service.save_loyalty_settings(
        replace(current, enabled=not current.enabled)
    )
    notice = "Loyalty program enabled." if updated.enabled else "Loyalty program disabled."
    await _render_loyalty_settings_message(callback.message, session, state, notice=notice, settings=updated)
    await callback.answer("Loyalty setting updated.")


@router.callback_query(F.data == AdminLoyaltyCallback.TOGGLE_AUTO_EARN.value)
async def handle_loyalty_toggle_auto_earn(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    current = await config_service.get_loyalty_settings()
    updated = await config_service.save_loyalty_settings(
        replace(current, auto_earn=not current.auto_earn)
    )
    notice = "Automatic earning enabled." if updated.auto_earn else "Automatic earning disabled."
    await _render_loyalty_settings_message(callback.message, session, state, notice=notice, settings=updated)
    await callback.answer("Loyalty setting updated.")


@router.callback_query(F.data == AdminLoyaltyCallback.TOGGLE_AUTO_PROMPT.value)
async def handle_loyalty_toggle_auto_prompt(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    current = await config_service.get_loyalty_settings()
    updated = await config_service.save_loyalty_settings(
        replace(current, auto_prompt=not current.auto_prompt)
    )
    notice = "Checkout prompt enabled." if updated.auto_prompt else "Checkout prompt disabled."
    await _render_loyalty_settings_message(callback.message, session, state, notice=notice, settings=updated)
    await callback.answer("Loyalty setting updated.")


@router.callback_query(F.data == AdminLoyaltyCallback.SET_EARN_RATE.value)
async def handle_loyalty_set_earn_rate(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminLoyaltyState.set_earn_rate)
    await callback.message.answer(
        "Send the number of loyalty points awarded per currency unit spent (e.g., 1.5).\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminLoyaltyCallback.SET_REDEEM_RATIO.value)
async def handle_loyalty_set_redeem_ratio(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminLoyaltyState.set_redeem_ratio)
    await callback.message.answer(
        "Send the currency value of a single point (e.g., 0.01).\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminLoyaltyCallback.SET_MIN_REDEEM.value)
async def handle_loyalty_set_min_redeem(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminLoyaltyState.set_min_redeem)
    await callback.message.answer(
        "Send the minimum number of points a user must have before redeeming.\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminLoyaltyCallback.BACK.value)
async def handle_loyalty_back(callback: CallbackQuery, session: AsyncSession) -> None:
    await handle_admin_menu(callback, session)

@router.callback_query(F.data == AdminOrderCallback.TOGGLE_PAYMENT_ALERT.value)
async def handle_toggle_payment_alert(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    alerts = await config_service.get_alert_settings()
    alerts.notify_payment = not alerts.notify_payment
    alerts = await config_service.save_alert_settings(alerts)
    notice = "Payment alerts enabled." if alerts.notify_payment else "Payment alerts disabled."
    await _render_order_settings_message(callback.message, session, alerts=alerts, notice=notice)
    await callback.answer("Payment alerts updated.")


@router.callback_query(F.data == AdminOrderCallback.TOGGLE_CANCEL_ALERT.value)
async def handle_toggle_cancel_alert(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    alerts = await config_service.get_alert_settings()
    alerts.notify_cancellation = not alerts.notify_cancellation
    alerts = await config_service.save_alert_settings(alerts)
    notice = "Cancellation alerts enabled." if alerts.notify_cancellation else "Cancellation alerts disabled."
    await _render_order_settings_message(callback.message, session, alerts=alerts, notice=notice)
    await callback.answer("Cancellation alerts updated.")


@router.callback_query(F.data == AdminOrderCallback.TOGGLE_EXPIRE_ALERT.value)
async def handle_toggle_expire_alert(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    alerts = await config_service.get_alert_settings()
    alerts.notify_expiration = not alerts.notify_expiration
    alerts = await config_service.save_alert_settings(alerts)
    notice = "Expiration alerts enabled." if alerts.notify_expiration else "Expiration alerts disabled."
    await _render_order_settings_message(callback.message, session, alerts=alerts, notice=notice)
    await callback.answer("Expiration alerts updated.")


@router.callback_query(F.data == AdminOrderCallback.VIEW_RECENT.value)
async def handle_orders_view_recent(callback: CallbackQuery, session: AsyncSession) -> None:
    rendered = await _render_recent_orders_message(callback.message, session, page=0)
    if not rendered:
        await callback.answer("No recent orders found.", show_alert=True)
    else:
        await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_RECENT_ORDERS_PAGE_PREFIX))
async def handle_orders_view_recent_page(callback: CallbackQuery, session: AsyncSession) -> None:
    raw = callback.data.removeprefix(ADMIN_RECENT_ORDERS_PAGE_PREFIX)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    rendered = await _render_recent_orders_message(callback.message, session, page=page)
    if not rendered:
        await callback.answer("No recent orders found.", show_alert=True)
    else:
        await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_ORDER_VIEW_PREFIX))
async def handle_admin_order_view(callback: CallbackQuery, session: AsyncSession) -> None:
    public_id = callback.data.removeprefix(ADMIN_ORDER_VIEW_PREFIX)
    await _render_admin_order_detail(callback.message, session, public_id)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_ORDER_TIMELINE_MENU_PREFIX))
async def handle_admin_order_timeline_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    public_id = callback.data.removeprefix(ADMIN_ORDER_TIMELINE_MENU_PREFIX)
    if public_id == callback.data:
        public_id = callback.data.removeprefix(LEGACY_ADMIN_ORDER_TIMELINE_MENU_PREFIX)
    if public_id == callback.data or not public_id:
        await callback.answer("Invalid timeline request.", show_alert=True)
        return
    if callback.message:
        await state.update_data(
            timeline_public_id=public_id,
            timeline_chat_id=callback.message.chat.id,
            timeline_message_id=callback.message.message_id,
        )
    await state.set_state(None)
    await _render_admin_order_detail(
        callback.message,
        session,
        public_id,
        notice="Timeline tools: choose a status or add an internal note.",
        reply_markup_override=lambda current_order, current_timeline: order_timeline_menu_keyboard(
            current_order,
            timeline=current_timeline,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_ORDER_TIMELINE_STATUS_PREFIX))
async def handle_admin_order_timeline_status(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    raw = callback.data.removeprefix(ADMIN_ORDER_TIMELINE_STATUS_PREFIX)
    if raw == callback.data:
        raw = callback.data.removeprefix(LEGACY_ADMIN_ORDER_TIMELINE_STATUS_PREFIX)
    if raw == callback.data or not raw:
        await callback.answer("Invalid timeline update.", show_alert=True)
        return
    try:
        status_key, public_id = raw.split(":", 1)
    except ValueError:
        await callback.answer("Invalid timeline update.", show_alert=True)
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None:
        await callback.answer("Order not found.", show_alert=True)
        if callback.message:
            await _render_recent_orders_message(callback.message, session, notice="Order removed.")
        return

    actor = f"admin:{callback.from_user.id}"
    timeline_service = OrderTimelineService(session)
    notice_text: str
    answer_text = "Timeline updated."
    if status_key == "cancelled":
        if order.status != OrderStatus.CANCELLED:
            reason = "admin_timeline_cancelled"
            await order_service.mark_cancelled(order, actor=actor)
            await session.flush()
            await refund_loyalty_for_order(session, order, reason=reason)
            await release_coupon_for_order(session, order, reason=reason)
            await cancel_referral_for_order(session, order, reason=reason)
            notifications = OrderNotificationService(session)
            await notifications.notify_cancelled(callback.bot, order, reason=reason)
            notice_text = "Order cancelled and recorded on the timeline."
            answer_text = "Order cancelled."
        else:
            notice_text = "Order already cancelled."
            answer_text = "Order already cancelled."
    else:
        label = OrderTimelineService.label_for_status(status_key)
        await timeline_service.add_event(order, status=status_key, actor=actor)
        notice_text = f"{label} recorded on timeline."
        answer_text = f"{label} logged."

    if callback.message:
        await state.update_data(
            timeline_public_id=public_id,
            timeline_chat_id=callback.message.chat.id,
            timeline_message_id=callback.message.message_id,
        )

    await _render_admin_order_detail(
        callback.message,
        session,
        public_id,
        notice=notice_text,
        reply_markup_override=order_timeline_menu_keyboard,
    )
    await callback.answer(answer_text)


@router.callback_query(F.data.startswith(ADMIN_ORDER_TIMELINE_NOTE_PREFIX))
async def handle_admin_order_timeline_note_prompt(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    public_id = callback.data.removeprefix(ADMIN_ORDER_TIMELINE_NOTE_PREFIX)
    if public_id == callback.data:
        public_id = callback.data.removeprefix(LEGACY_ADMIN_ORDER_TIMELINE_NOTE_PREFIX)
    if public_id == callback.data or not public_id:
        await callback.answer("Invalid timeline note request.", show_alert=True)
        return
    if callback.message:
        await state.update_data(
            timeline_public_id=public_id,
            timeline_chat_id=callback.message.chat.id,
            timeline_message_id=callback.message.message_id,
        )
    await state.set_state(AdminOrderTimelineState.add_note)
    await _render_admin_order_detail(
        callback.message,
        session,
        public_id,
        notice="Send the note text to append it to the timeline. Use /cancel to abort.",
        reply_markup_override=order_timeline_menu_keyboard,
    )
    await callback.answer("Waiting for note text…")


@router.message(AdminOrderTimelineState.add_note)
async def handle_admin_order_timeline_note_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    public_id = data.get("timeline_public_id")
    chat_id = data.get("timeline_chat_id")
    target_message_id = data.get("timeline_message_id")

    if not public_id:
        await message.answer("Timeline context expired. Please reopen the order.")
        await state.set_state(None)
        return

    if text.lower() in {"/cancel", "cancel", "exit", "abort"}:
        await _render_admin_order_detail(
            None,
            session,
            public_id,
            notice="Timeline note entry cancelled.",
            reply_markup_override=order_timeline_menu_keyboard,
            bot=message.bot,
            chat_id=chat_id,
            message_id=target_message_id,
        )
        await message.answer("Cancelled.")
        await state.update_data(
            timeline_public_id=None,
            timeline_chat_id=None,
            timeline_message_id=None,
        )
        await state.set_state(None)
        return

    if not text:
        await message.answer("Please send a non-empty note or /cancel.")
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None:
        await message.answer("Order not found. Please refresh the admin panel.")
        await state.update_data(
            timeline_public_id=None,
            timeline_chat_id=None,
            timeline_message_id=None,
        )
        await state.set_state(None)
        return

    actor = f"admin:{message.from_user.id}"
    timeline_service = OrderTimelineService(session)
    await timeline_service.add_event(
        order,
        event_type="note",
        note=text,
        actor=actor,
    )

    await _render_admin_order_detail(
        None,
        session,
        public_id,
        notice="Timeline note added.",
        reply_markup_override=order_timeline_menu_keyboard,
        bot=message.bot,
        chat_id=chat_id,
        message_id=target_message_id,
    )

    await message.answer("Note saved to timeline.")
    await state.update_data(
        timeline_public_id=None,
        timeline_chat_id=None,
        timeline_message_id=None,
    )
    await state.set_state(None)


@router.callback_query(F.data.startswith(ADMIN_ORDER_MARK_PAID_PREFIX))
async def handle_admin_order_mark_paid(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(ADMIN_ORDER_MARK_PAID_PREFIX)
    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None:
        await callback.answer("Order not found.", show_alert=True)
        await _render_recent_orders_message(callback.message, session, notice="Order removed.")
        return
    if order.status == OrderStatus.PAID:
        await callback.answer("Order is already marked as paid.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return
    if order.status not in {OrderStatus.AWAITING_PAYMENT, OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
        await callback.answer("Order cannot be marked as paid in its current state.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return
    await session.refresh(order, attribute_names=["product"])
    product = order.product
    if product is None or not product.is_active:
        await callback.answer("Product is not active.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return
    charge_id = f"manual:{datetime.now(tz=timezone.utc).isoformat()}"
    await order_service.mark_paid(order, charge_id=charge_id, actor=f"admin:{callback.from_user.id}")
    order.invoice_payload = None
    order.payment_provider = "manual"
    await ensure_fulfillment(session, callback.bot, order, source="admin_manual_paid")

    state_data = await state.get_data()
    using_timeline = state_data.get("timeline_public_id") == public_id
    if using_timeline and callback.message:
        await state.update_data(
            timeline_public_id=public_id,
            timeline_chat_id=callback.message.chat.id,
            timeline_message_id=callback.message.message_id,
        )
    elif using_timeline:
        await state.update_data(
            timeline_public_id=None,
            timeline_chat_id=None,
            timeline_message_id=None,
        )
    else:
        await state.update_data(
            timeline_public_id=None,
            timeline_chat_id=None,
            timeline_message_id=None,
        )

    await _render_admin_order_detail(
        callback.message,
        session,
        public_id,
        notice="Order marked as paid.",
        reply_markup_override=order_timeline_menu_keyboard if using_timeline else None,
    )
    await callback.answer("Order marked as paid.")


@router.callback_query(F.data.startswith(ADMIN_ORDER_MARK_FULFILLED_PREFIX))
async def handle_admin_order_mark_fulfilled(callback: CallbackQuery, session: AsyncSession) -> None:
    public_id = callback.data.removeprefix(ADMIN_ORDER_MARK_FULFILLED_PREFIX)
    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None:
        await callback.answer("Order not found.", show_alert=True)
        await _render_recent_orders_message(callback.message, session, notice="Order removed.")
        return
    if order.status != OrderStatus.PAID:
        await callback.answer("Order is not marked as paid yet.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return
    await session.refresh(order, attribute_names=["product", "user"])
    delivered = await ensure_fulfillment(session, callback.bot, order, source="admin_manual")
    if delivered:
        notice = "Fulfillment executed successfully."
        await _render_admin_order_detail(callback.message, session, public_id, notice=notice)
        await callback.answer("Fulfillment executed.")
    else:
        notice = "Order already fulfilled."
        await _render_admin_order_detail(callback.message, session, public_id, notice=notice)
        await callback.answer("Order was already fulfilled.", show_alert=True)


@router.callback_query(F.data.startswith(ADMIN_ORDER_NOTIFY_DELIVERED_PREFIX))
async def handle_admin_order_notify_delivered(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    public_id = callback.data.removeprefix(ADMIN_ORDER_NOTIFY_DELIVERED_PREFIX)
    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None:
        await callback.answer("Order not found.", show_alert=True)
        await _render_recent_orders_message(callback.message, session, notice="Order removed.")
        return

    if order.status != OrderStatus.PAID:
        await callback.answer("Order must be marked as paid first.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return

    await session.refresh(order, attribute_names=["user", "product"])
    if order.user is None or order.user.telegram_id is None:
        await callback.answer("User contact information is missing.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return

    meta = dict(_extract_oxapay_meta(order))
    delivery_meta = meta.get("delivery_notice") if isinstance(meta, dict) else None
    if isinstance(delivery_meta, dict) and delivery_meta.get("sent_at"):
        await callback.answer("Delivery notice already sent.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return

    message_text = _format_delivery_notice(order, meta=meta)
    try:
        sent_message = await callback.bot.send_message(order.user.telegram_id, message_text)
    except Exception:
        await callback.answer("Failed to notify the customer.", show_alert=True)
        return

    timestamp = datetime.now(tz=timezone.utc).isoformat()
    delivery_record = {
        "sent_at": timestamp,
        "sent_by": "admin_manual_delivery",
        "recipient": order.user.telegram_id,
    }
    if sent_message is not None:
        delivery_record["message_id"] = sent_message.message_id

    meta["delivery_notice"] = delivery_record
    await OrderRepository(session).merge_extra_attrs(order, {OXAPAY_EXTRA_KEY: meta})
    order.extra_attrs = order.extra_attrs or {}
    order.extra_attrs[OXAPAY_EXTRA_KEY] = meta

    timeline_service = OrderTimelineService(session)
    await timeline_service.add_event(
        order,
        event_type="note",
        note="Delivery notice sent to the customer.",
        actor=f"admin:{callback.from_user.id}",
    )

    state_data = await state.get_data()
    using_timeline = state_data.get("timeline_public_id") == public_id
    if using_timeline and callback.message:
        await state.update_data(
            timeline_public_id=public_id,
            timeline_chat_id=callback.message.chat.id,
            timeline_message_id=callback.message.message_id,
        )
    elif using_timeline:
        await state.update_data(
            timeline_public_id=None,
            timeline_chat_id=None,
            timeline_message_id=None,
        )
    else:
        await state.update_data(
            timeline_public_id=None,
            timeline_chat_id=None,
            timeline_message_id=None,
        )

    notice = "Delivery notice sent to the customer."
    await _render_admin_order_detail(
        callback.message,
        session,
        public_id,
        notice=notice,
        reply_markup_override=order_timeline_menu_keyboard if using_timeline else None,
    )
    await callback.answer("Customer notified.")


@router.callback_query(F.data.startswith(ADMIN_ORDER_RECEIPT_PREFIX))
async def handle_admin_order_receipt(callback: CallbackQuery, session: AsyncSession) -> None:
    public_id = callback.data.removeprefix(ADMIN_ORDER_RECEIPT_PREFIX)
    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None:
        await callback.answer("Order not found.", show_alert=True)
        await _render_recent_orders_message(callback.message, session, notice="Order removed.")
        return
    if order.user is None or order.user.telegram_id is None:
        await callback.answer("User contact information is missing.", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return

    receipt_text = _format_order_receipt(order)
    try:
        await callback.bot.send_message(order.user.telegram_id, receipt_text)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(f"Failed to send receipt: {exc}", show_alert=True)
        await _render_admin_order_detail(callback.message, session, public_id)
        return

    await _render_admin_order_detail(callback.message, session, public_id, notice="Receipt sent to customer.")
    await callback.answer("Receipt sent to customer.")


@router.callback_query(F.data == AdminOrderCallback.BACK.value)
async def handle_orders_back(callback: CallbackQuery, session: AsyncSession) -> None:
    await handle_admin_menu(callback, session)


@router.callback_query(F.data == AdminMenuCallback.TOGGLE_SUBSCRIPTION.value)
async def handle_toggle_subscription(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    current = await config_service.subscription_required()
    new_value = not current
    await config_service.set_subscription_required(new_value)

    await callback.message.edit_text(
        f"Admin control panel (subscription gate {'enabled' if new_value else 'disabled'}).",
        reply_markup=admin_menu_keyboard(subscription_enabled=new_value),
    )
    await callback.answer(
        "Subscription gate enabled." if new_value else "Subscription gate disabled."
    )


@router.callback_query(F.data == AdminMenuCallback.MANAGE_CRYPTO.value)
async def handle_manage_crypto(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(None)
    await _render_crypto_settings_message(callback.message, session, state)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.BACK.value)
async def handle_crypto_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await handle_admin_menu(callback, session)


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_ENABLED.value)
async def handle_crypto_toggle_enabled(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    settings = get_settings()
    if not config.enabled and not settings.oxapay_api_key:
        await callback.answer("OXAPAY_API_KEY is not configured.", show_alert=True)
        return
    config.enabled = not config.enabled
    config = await config_service.save_crypto_settings(config)
    notice = "Crypto payments enabled." if config.enabled else "Crypto payments disabled."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_MIXED.value)
async def handle_crypto_toggle_mixed(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.mixed_payment = not config.mixed_payment
    config = await config_service.save_crypto_settings(config)
    notice = f"Mixed payments {'enabled' if config.mixed_payment else 'disabled'}."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_FEE_PAYER.value)
async def handle_crypto_toggle_fee_payer(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.fee_payer = "merchant" if config.fee_payer == "payer" else "payer"
    config = await config_service.save_crypto_settings(config)
    notice = f"Fee will be paid by {'customer' if config.fee_payer == 'payer' else 'merchant'}."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.TOGGLE_AUTO_WITHDRAWAL.value)
async def handle_crypto_toggle_withdrawal(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.auto_withdrawal = not config.auto_withdrawal
    config = await config_service.save_crypto_settings(config)
    notice = f"Auto withdrawal {'enabled' if config.auto_withdrawal else 'disabled'}."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.REFRESH_ACCEPTED.value)
async def handle_crypto_refresh_accepted(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    service = CryptoPaymentService(session)
    currencies = await service.list_accepted_currencies()
    if currencies:
        notice = "Account accepts: " + ", ".join(currencies)
    else:
        notice = "Unable to fetch accepted currencies. Check API key or permissions."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.VIEW_PENDING.value)
async def handle_crypto_view_pending(callback: CallbackQuery, session: AsyncSession) -> None:
    repo = OrderRepository(session)
    orders = await repo.list_pending_crypto(limit=10)
    if not orders:
        await callback.message.answer("No open crypto invoices.")
        await callback.answer()
        return

    text = _format_pending_orders(orders)
    await callback.message.answer(text, disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SYNC_PENDING.value)
async def handle_crypto_sync_pending(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    repo = OrderRepository(session)
    orders = await repo.list_pending_crypto(limit=10)
    if not orders:
        await callback.answer("No open invoices to sync.", show_alert=True)
        return

    service = CryptoPaymentService(session)
    order_service = OrderService(session)
    notifications = OrderNotificationService(session)
    updated = 0
    for order in orders:
        previous_status = order.status
        result = await service.refresh_order_status(order)
        if result.updated:
            updated += 1
            if order.status == OrderStatus.CANCELLED:
                await notifications.notify_cancelled(callback.bot, order, reason="provider_update")
                await refund_loyalty_for_order(session, order, reason="provider_update")
                await release_coupon_for_order(session, order, reason="provider_update")
                await cancel_referral_for_order(session, order, reason="provider_update")
            elif order.status == OrderStatus.EXPIRED:
                await notifications.notify_expired(callback.bot, order, reason="provider_update")
                await refund_loyalty_for_order(session, order, reason="provider_update")
                await release_coupon_for_order(session, order, reason="provider_update")
                await cancel_referral_for_order(session, order, reason="provider_update")
        if order.status == OrderStatus.PAID:
            await ensure_fulfillment(session, callback.bot, order, source="admin_sync")
            continue

        enforced_before = order.status
        await order_service.enforce_expiration(order)
        if (
            order.status == OrderStatus.EXPIRED
            and enforced_before != OrderStatus.EXPIRED
            and previous_status != OrderStatus.EXPIRED
        ):
            await notifications.notify_expired(callback.bot, order, reason="admin_sync_timeout")
            await refund_loyalty_for_order(session, order, reason="admin_sync_timeout")
            await release_coupon_for_order(session, order, reason="admin_sync_timeout")
            await cancel_referral_for_order(session, order, reason="admin_sync_timeout")

    notice = f"Synced {len(orders)} invoice(s). Updated: {updated}."
    await _render_crypto_settings_message(callback.message, session, state, notice=notice)
    await callback.answer("Sync complete.")


@router.callback_query(F.data == AdminCryptoCallback.SET_CURRENCIES.value)
async def handle_crypto_prompt_currencies(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.currencies)
    service = CryptoPaymentService(session)
    currencies = await service.list_accepted_currencies()
    hint = ""
    if currencies:
        hint = f"\nSupported by OxaPay account: {', '.join(currencies)}"
    await callback.message.answer(
        "Send the comma-separated list of currency symbols to accept (e.g., USDT,BTC)."
        "\nSend /cancel to abort."
        f"{hint}"
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_LIFETIME.value)
async def handle_crypto_prompt_lifetime(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.lifetime)
    await callback.message.answer(
        "Send the invoice lifetime in minutes (15 - 2880)."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_UNDERPAID.value)
async def handle_crypto_prompt_underpaid(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.underpaid)
    await callback.message.answer(
        "Send the acceptable underpaid coverage percentage (0 - 60)."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_TO_CURRENCY.value)
async def handle_crypto_prompt_to_currency(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.to_currency)
    await callback.message.answer(
        "Send the settlement currency symbol (e.g., USDT)."
        "\nSend 'clear' to disable conversion."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_RETURN_URL.value)
async def handle_crypto_prompt_return_url(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.return_url)
    await callback.message.answer(
        "Send the return URL for successful payments."
        "\nSend 'clear' to remove."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_CALLBACK_URL.value)
async def handle_crypto_prompt_callback_url(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.callback_url)
    await callback.message.answer(
        "Send the callback (webhook) URL to receive payment notifications."
        "\nSend 'clear' to remove."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminCryptoCallback.SET_CALLBACK_SECRET.value)
async def handle_crypto_prompt_callback_secret(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminCryptoState.callback_secret)
    await callback.message.answer(
        "Send the callback secret used to verify webhook signatures."
        "\nSend 'clear' to remove."
        "\nSend /cancel to abort."
    )
    await callback.answer()


@router.callback_query(F.data == AdminMenuCallback.MANAGE_CHANNELS.value)
async def handle_manage_channels(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    enabled = await config_service.subscription_required()

    await callback.message.edit_text(
        "Channel management will be available soon. You will be able to configure required subscriptions here.",
        reply_markup=admin_menu_keyboard(subscription_enabled=enabled),
    )
    await callback.answer()


@router.callback_query(F.data == AdminMenuCallback.BACK_TO_MAIN.value)
async def handle_admin_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Welcome to Ben Bot!\nUse the interactive menu below to browse products, manage orders, or contact support.",
        reply_markup=main_menu_keyboard(show_admin=True),
    )
    await callback.answer()


@router.message(AdminCryptoState.currencies)
async def process_crypto_currencies(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send one or more currency symbols separated by commas, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    tokens = [item.strip().upper() for item in text.replace("\n", ",").split(",") if item.strip()]
    if not tokens:
        await message.answer("Please send at least one currency symbol, or /cancel.")
        return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.currencies = tokens
    await config_service.save_crypto_settings(config)
    await message.answer("Allowed currencies updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Allowed currencies updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.lifetime)
async def process_crypto_lifetime(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send an integer value between 15 and 2880 minutes, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    try:
        value = int(text)
    except ValueError:
        await message.answer("Please send a valid integer number of minutes.")
        return
    if value < 15 or value > 2880:
        await message.answer("The lifetime must be between 15 and 2880 minutes.")
        return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.lifetime_minutes = value
    await config_service.save_crypto_settings(config)
    await message.answer("Invoice lifetime updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Invoice lifetime updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.underpaid)
async def process_crypto_underpaid(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please send a percentage between 0 and 60, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    try:
        value = float(text)
    except ValueError:
        await message.answer("Please send a numeric percentage (e.g., 5 or 12.5).")
        return
    if value < 0 or value > 60:
        await message.answer("The underpaid coverage must be between 0 and 60%.")
        return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.underpaid_coverage = value
    await config_service.save_crypto_settings(config)
    await message.answer("Underpaid coverage updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Underpaid coverage updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.to_currency)
async def process_crypto_to_currency(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send a settlement currency symbol (e.g., USDT), 'clear' to disable, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    if text.lower() in {"clear", "none", "-"}:
        token = None
    else:
        token = text.upper()
        if not re.fullmatch(r"[A-Z0-9]{2,10}", token):
            await message.answer("Please send a valid currency symbol (2-10 alphanumeric characters).")
            return
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.to_currency = token
    await config_service.save_crypto_settings(config)
    await message.answer("Settlement currency updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Settlement currency updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.return_url)
async def process_crypto_return_url(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the return URL, 'clear' to remove it, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    url = None if text.lower() in {"clear", "none", "-"} else text
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.return_url = url
    await config_service.save_crypto_settings(config)
    await message.answer("Return URL updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Return URL updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.callback_url)
async def process_crypto_callback_url(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the callback URL, 'clear' to remove it, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    url = None if text.lower() in {"clear", "none", "-"} else text
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.callback_url = url
    await config_service.save_crypto_settings(config)
    await message.answer("Callback URL updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Callback URL updated.")
    await state.set_state(None)


@router.message(AdminCryptoState.callback_secret)
async def process_crypto_callback_secret(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the callback secret, 'clear' to remove it, or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_crypto_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    secret = None if text.lower() in {"clear", "none", "-"} else text
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    config.callback_secret = secret
    await config_service.save_crypto_settings(config)
    await message.answer("Callback secret updated.")
    await _update_crypto_settings_message_from_state(message, session, state, notice="Callback secret updated.")
    await state.set_state(None)


@router.message(AdminLoyaltyState.set_earn_rate)
async def process_loyalty_earn_rate(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send a numeric value (e.g., 1 or 1.5), or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_loyalty_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    try:
        value = float(text)
    except ValueError:
        await message.answer("Please send a numeric value (e.g., 1 or 1.5).")
        return
    if value < 0:
        await message.answer("Earn rate cannot be negative.")
        return
    config_service = ConfigService(session)
    current = await config_service.get_loyalty_settings()
    updated = await config_service.save_loyalty_settings(
        replace(current, points_per_currency=value)
    )
    await message.answer("Earn rate updated.")
    await _update_loyalty_settings_message_from_state(message, session, state, notice="Earn rate updated.", settings=updated)
    await state.set_state(None)


@router.message(AdminLoyaltyState.set_redeem_ratio)
async def process_loyalty_redeem_ratio(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the currency value of one point (e.g., 0.01), or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_loyalty_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    try:
        value = float(text)
    except ValueError:
        await message.answer("Please send a numeric value (e.g., 0.01).")
        return
    if value <= 0:
        await message.answer("The redeem ratio must be greater than zero.")
        return
    config_service = ConfigService(session)
    current = await config_service.get_loyalty_settings()
    updated = await config_service.save_loyalty_settings(
        replace(current, redeem_ratio=value)
    )
    await message.answer("Redeem ratio updated.")
    await _update_loyalty_settings_message_from_state(message, session, state, notice="Redeem ratio updated.", settings=updated)
    await state.set_state(None)


@router.message(AdminLoyaltyState.set_min_redeem)
async def process_loyalty_min_redeem(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Send the minimum redeemable points (integer), or /cancel.")
        return
    if _is_cancel(text):
        await message.answer("Operation cancelled.")
        await _update_loyalty_settings_message_from_state(message, session, state)
        await state.set_state(None)
        return
    try:
        value = int(text)
    except ValueError:
        await message.answer("Please send a valid integer value.")
        return
    if value < 0:
        await message.answer("Minimum redeem points cannot be negative.")
        return
    config_service = ConfigService(session)
    current = await config_service.get_loyalty_settings()
    updated = await config_service.save_loyalty_settings(
        replace(current, min_redeem_points=value)
    )
    await message.answer("Minimum redeem points updated.")
    await _update_loyalty_settings_message_from_state(message, session, state, notice="Minimum redeem points updated.", settings=updated)
    await state.set_state(None)


async def _render_order_settings_message(
    message: Message,
    session: AsyncSession,
    *,
    alerts: ConfigService.AlertSettings | None = None,
    notice: str | None = None,
) -> None:
    config_service = ConfigService(session)
    current = alerts or await config_service.get_alert_settings()
    text = _format_order_alerts_text(current)
    if notice:
        text = f"{notice}\n\n{text}"
    markup = order_settings_keyboard(current)
    try:
        await message.edit_text(text, reply_markup=markup)
    except Exception:
        await message.answer(text, reply_markup=markup)


async def _render_recent_orders_message(
    message: Message,
    session: AsyncSession,
    *,
    notice: str | None = None,
    page: int = 0,
) -> bool:
    repo = OrderRepository(session)
    offset = max(page, 0) * RECENT_ORDERS_PAGE_SIZE
    orders, has_more = await repo.paginate_recent(limit=RECENT_ORDERS_PAGE_SIZE, offset=offset)
    has_prev = page > 0 and offset > 0

    if not orders and page > 0:
        page = max(page - 1, 0)
        offset = page * RECENT_ORDERS_PAGE_SIZE
        orders, has_more = await repo.paginate_recent(limit=RECENT_ORDERS_PAGE_SIZE, offset=offset)
        has_prev = page > 0 and offset > 0

    if not orders:
        await _render_order_settings_message(
            message,
            session,
            notice=notice or "No recent orders found.",
        )
        return False

    text = _format_recent_orders_text(
        orders,
        page=page,
        page_size=RECENT_ORDERS_PAGE_SIZE,
        has_prev=has_prev,
        has_next=has_more,
    )
    if notice:
        text = f"{notice}\n\n{text}"
    markup = recent_orders_keyboard(
        orders,
        page=page,
        has_prev=has_prev,
        has_next=has_more,
    )
    try:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except Exception:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    return True


async def _render_admin_order_detail(
    message: Message | None,
    session: AsyncSession,
    public_id: str,
    *,
    notice: str | None = None,
    reply_markup_override: InlineKeyboardMarkup
    | Callable[[Order, Sequence[OrderTimeline] | None], InlineKeyboardMarkup]
    | None = None,
    bot=None,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> None:
    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None:
        if message is not None:
            await _render_recent_orders_message(message, session, notice="Order no longer exists.")
        elif bot and chat_id and message_id:
            try:
                await bot.edit_message_text(
                    "Order no longer exists.",
                    chat_id=chat_id,
                    message_id=message_id,
                )
            except Exception:
                pass
        return

    try:
        await session.refresh(order, attribute_names=["user", "product"])
    except Exception:
        pass

    timeline_service = OrderTimelineService(session)
    timeline = await timeline_service.list_events(order)

    text = _format_admin_order_detail(order, timeline)
    if notice:
        text = f"{notice}\n\n{text}"
    if callable(reply_markup_override):
        markup = reply_markup_override(order, timeline)
    else:
        markup = reply_markup_override or order_manage_keyboard(order)
    if message is not None:
        try:
            await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        except Exception:
            await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    elif bot and chat_id and message_id:
        try:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception:
            await bot.send_message(
                chat_id,
                text,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
    else:
        return


async def _render_crypto_settings_message(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    notice: str | None = None,
) -> None:
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    repo = OrderRepository(session)
    stats = await repo.crypto_status_counts()
    text = _format_crypto_settings_text(
        config,
        stats=stats,
        api_key_present=bool(get_settings().oxapay_api_key),
    )
    if notice:
        text = f"{notice}\n\n{text}"
    markup = crypto_settings_keyboard(config)
    try:
        await message.edit_text(text, reply_markup=markup)
        target = message
    except Exception:
        target = await message.answer(text, reply_markup=markup)
    await state.update_data(crypto_chat_id=target.chat.id, crypto_message_id=target.message_id)


async def _update_crypto_settings_message_from_state(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    notice: str | None = None,
) -> None:
    data = await state.get_data()
    chat_id = data.get("crypto_chat_id")
    message_id = data.get("crypto_message_id")
    config_service = ConfigService(session)
    config = await config_service.get_crypto_settings()
    repo = OrderRepository(session)
    stats = await repo.crypto_status_counts()
    text = _format_crypto_settings_text(
        config,
        stats=stats,
        api_key_present=bool(get_settings().oxapay_api_key),
    )
    if notice:
        text = f"{notice}\n\n{text}"
    markup = crypto_settings_keyboard(config)
    if chat_id and message_id:
        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            return
        except Exception:
            pass
    target = await message.answer(text, reply_markup=markup)
    await state.update_data(crypto_chat_id=target.chat.id, crypto_message_id=target.message_id)



def _format_pending_orders(orders: list[Order]) -> str:
    lines = ["<b>Open invoices (latest 10)</b>"]
    for order in orders:
        meta = _extract_oxapay_meta(order)
        lines.append("")
        lines.append(f"<code>{order.public_id}</code>")
        lines.append(f"User ID: {order.user_id}")
        lines.append(f"Total: {order.total_amount} {order.currency}")
        if order.created_at:
            lines.append(f"Created: {order.created_at:%Y-%m-%d %H:%M UTC}")
        track_id = meta.get("track_id") or order.invoice_payload or "-"
        lines.append(f"Track ID: {track_id}")
        if order.payment_expires_at:
            lines.append(f"Expires: {order.payment_expires_at:%Y-%m-%d %H:%M UTC}")
        status = meta.get("status") or order.status.value
        lines.append(f"Status: {status}")
        if meta.get("updated_at"):
            lines.append(f"Last update: {meta['updated_at']}")
        if meta.get("pay_link"):
            lines.append(f"Link: {meta['pay_link']}")
    return "\n".join(lines)


def _extract_oxapay_meta(order: Order) -> dict[str, Any]:
    extra = order.extra_attrs or {}
    meta = extra.get(OXAPAY_EXTRA_KEY)
    return meta if isinstance(meta, dict) else {}


def _format_crypto_settings_text(
    config: ConfigService.CryptoSettings,
    *,
    stats: dict[OrderStatus, int],
    api_key_present: bool,
) -> str:
    lines = [
        "<b>OxaPay crypto payments</b>",
        f"Status: {'✅ Enabled' if config.enabled else '❌ Disabled'}",
    ]
    if not api_key_present:
        lines.append("⚠️ OXAPAY_API_KEY is not configured. Enable payments after setting the API key.")
    lines.append(f"Allowed currencies: {', '.join(config.currencies) if config.currencies else '-'}")
    lines.append(f"Invoice lifetime: {config.lifetime_minutes} minutes")
    lines.append(f"Mixed payment: {'ON' if config.mixed_payment else 'OFF'}")
    lines.append(f"Fee payer: {'Customer' if config.fee_payer == 'payer' else 'Merchant'}")
    lines.append(f"Underpaid coverage: {config.underpaid_coverage}%")
    lines.append(f"Auto withdrawal: {'ON' if config.auto_withdrawal else 'OFF'}")
    lines.append(f"Settlement currency: {config.to_currency or '-'}")
    lines.append(f"Return URL: {config.return_url or '-'}")
    lines.append(f"Callback URL: {config.callback_url or '-'}")
    lines.append(f"Callback secret: {'set' if config.callback_secret else '-'}")
    if stats:
        awaiting = stats.get(OrderStatus.AWAITING_PAYMENT, 0)
        paid = stats.get(OrderStatus.PAID, 0)
        expired = stats.get(OrderStatus.EXPIRED, 0)
        cancelled = stats.get(OrderStatus.CANCELLED, 0)
        lines.append("")
        lines.append("<b>Invoice summary</b>")
        lines.append(f"Awaiting payment: {awaiting}")
        if paid:
            lines.append(f"Paid recently: {paid}")
        if expired:
            lines.append(f"Expired: {expired}")
        if cancelled:
            lines.append(f"Cancelled: {cancelled}")
    lines.append("\nUse the buttons below to update settings.")
    return "\n".join(lines)


def _format_order_alerts_text(alerts: ConfigService.AlertSettings) -> str:
    lines = [
        "<b>Order notification settings</b>",
        f"Payment alerts: {'ON' if alerts.notify_payment else 'OFF'}",
        f"Cancellation alerts: {'ON' if alerts.notify_cancellation else 'OFF'}",
        f"Expiration alerts: {'ON' if alerts.notify_expiration else 'OFF'}",
        "",
        "These alerts send direct messages to the bot owners.",
    ]
    return "\n".join(lines)


def _format_recent_orders_text(
    orders: list[Order],
    *,
    page: int,
    page_size: int,
    has_prev: bool,
    has_next: bool,
) -> str:
    lines = ["<b>Recent orders</b>"]
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
        status = order.status.value.replace("_", " ").title()
        created = order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "-"
        product_name = getattr(order.product, "name", "-")
        amount = f"{order.total_amount} {order.currency}"
        lines.append(f"{idx}. {status} - {amount} - {product_name}")
        lines.append(f"User: {order.user_id} - Public ID: <code>{order.public_id}</code> - Created: {created}")
    lines.append("")
    lines.append("Select an order below to view details.")
    return "\n".join(lines)


def _format_admin_order_detail(
    order: Order,
    timeline: list[OrderTimeline] | None = None,
) -> str:
    lines = [
        f"<b>Order {order.public_id}</b>",
        f"Status: {order.status.value.replace('_', ' ').title()}",
        f"Total: {order.total_amount} {order.currency}",
        f"User ID: {order.user_id}",
    ]
    if order.user:
        lines.append(f"Customer: {order.user.display_name()} (telegram_id={order.user.telegram_id})")
    if order.product:
        lines.append(f"Product: {order.product.name}")
    if order.created_at:
        lines.append(f"Created: {order.created_at:%Y-%m-%d %H:%M:%S UTC}")
    if order.updated_at:
        lines.append(f"Updated: {order.updated_at:%Y-%m-%d %H:%M:%S UTC}")

    if order.invoice_payload:
        lines.append(f"Track/Invoice ID: {order.invoice_payload}")
    if order.payment_provider:
        lines.append(f"Provider: {order.payment_provider}")

    oxapay_meta = _extract_oxapay_meta(order)
    if oxapay_meta:
        lines.append("")
        lines.append("<b>Payment metadata</b>")
        if oxapay_meta.get("status"):
            lines.append(f"Provider status: {oxapay_meta.get('status')}")
        if oxapay_meta.get("pay_link"):
            lines.append(f"Link: {oxapay_meta.get('pay_link')}")
        if oxapay_meta.get("updated_at"):
            lines.append(f"Last sync: {oxapay_meta.get('updated_at')}")
        if oxapay_meta.get("track_id"):
            lines.append(f"Track ID: {oxapay_meta.get('track_id')}")

    fulfillment = oxapay_meta.get("fulfillment") if isinstance(oxapay_meta, dict) else None
    if fulfillment:
        lines.append("")
        lines.append("<b>Fulfillment</b>")
        if fulfillment.get("delivered_at"):
            lines.append(f"Delivered at: {fulfillment.get('delivered_at')}")
        if fulfillment.get("delivered_by"):
            lines.append(f"Source: {fulfillment.get('delivered_by')}")
        context = fulfillment.get("context") or {}
        if context.get("license_code"):
            lines.append(f"License code: {context['license_code']}")
        actions = fulfillment.get("actions") or []
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_name = action.get("action", "?")
            status = action.get("status", "?")
            detail = action.get("detail")
            lines.append(f"{action_name}: {status}")
            if detail:
                lines.append(f" - {detail}")
            if action.get("error"):
                lines.append(f" - error: {action['error']}")

    delivery_notice = oxapay_meta.get("delivery_notice")
    if isinstance(delivery_notice, dict) and delivery_notice.get("sent_at"):
        lines.append("")
        lines.append("<b>Delivery notice</b>")
        lines.append(f"Sent at: {delivery_notice.get('sent_at')}")
        sender = delivery_notice.get("sent_by")
        if sender:
            lines.append(f"Source: {sender}")

    if timeline:
        lines.append("")
        lines.append("<b>Timeline</b>")
        for entry in timeline:
            lines.extend(_format_timeline_entry(entry))

    return "\n".join(lines)


def _format_timeline_entry(entry: OrderTimeline) -> list[str]:
    created_at = entry.created_at
    if created_at is not None:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_text = f"{created_at.astimezone(timezone.utc):%Y-%m-%d %H:%M:%S UTC}"
    else:
        created_text = "-"

    if entry.event_type == "note":
        label = "Note"
    else:
        label = OrderTimelineService.label_for_status(entry.status)

    actor = f" (by {entry.actor})" if entry.actor else ""
    lines = [f"{created_text} - {label}{actor}"]

    note = (entry.note or "").strip()
    if note:
        lines.append(f"  {note}")

    return lines


def _format_delivery_notice(order: Order, *, meta: dict[str, Any]) -> str:
    summary = build_order_summary(order)
    if summary.has_cart_items:
        headline = f"Order <code>{order.public_id}</code> has been delivered."
    else:
        headline = f"Order <code>{order.public_id}</code> for {summary.label} has been delivered."

    lines = [
        "<b>Delivery update</b>",
        headline,
    ]
    if summary.has_cart_items and summary.item_lines:
        lines.append("")
        lines.append("<b>Items</b>")
        lines.extend(summary.item_lines)
    if summary.has_cart_items and summary.totals_lines:
        lines.append("")
        lines.extend(summary.totals_lines)

    fulfillment = meta.get("fulfillment") if isinstance(meta, dict) else None
    context = (fulfillment or {}).get("context") or {}
    license_code = context.get("license_code")
    if license_code:
        lines.append("")
        lines.append(f"License code: <code>{license_code}</code>")
    lines.append("")
    lines.append("Thank you for your purchase! Let us know if you need anything else.")
    return "\n".join(lines)


def _format_order_receipt(order: Order) -> str:
    lines = [
        "<b>Payment receipt</b>",
        f"Order: <code>{order.public_id}</code>",
        f"Amount: {order.total_amount} {order.currency}",
        f"Status: {order.status.value.replace('_', ' ').title()}",
    ]
    if order.product:
        lines.append(f"Product: {order.product.name}")
    if order.created_at:
        lines.append(f"Created: {order.created_at:%Y-%m-%d %H:%M UTC}")
    if order.updated_at:
        lines.append(f"Updated: {order.updated_at:%Y-%m-%d %H:%M UTC}")
    oxapay_meta = _extract_oxapay_meta(order)
    if isinstance(oxapay_meta, dict):
        fulfillment = oxapay_meta.get("fulfillment") or {}
        context = fulfillment.get("context") or {}
        if context.get("license_code"):
            lines.append("")
            lines.append(f"License code: <code>{context['license_code']}</code>")
    lines.append("")
    lines.append("Thank you for your purchase!")
    return "\n".join(lines)


async def _render_loyalty_settings_message(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    notice: str | None = None,
    settings: ConfigService.LoyaltySettings | None = None,
) -> None:
    config_service = ConfigService(session)
    settings = settings or await config_service.get_loyalty_settings()
    text = _format_loyalty_settings_text(settings)
    if notice:
        text = f"{notice}\n\n{text}"
    markup = loyalty_settings_keyboard(settings)
    try:
        await message.edit_text(text, reply_markup=markup)
        target = message
    except Exception:
        target = await message.answer(text, reply_markup=markup)
    await state.update_data(
        loyalty_chat_id=target.chat.id,
        loyalty_message_id=target.message_id,
    )


async def _update_loyalty_settings_message_from_state(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    *,
    notice: str | None = None,
    settings: ConfigService.LoyaltySettings | None = None,
) -> None:
    data = await state.get_data()
    chat_id = data.get("loyalty_chat_id")
    message_id = data.get("loyalty_message_id")
    config_service = ConfigService(session)
    settings = settings or await config_service.get_loyalty_settings()
    text = _format_loyalty_settings_text(settings)
    if notice:
        text = f"{notice}\n\n{text}"
    markup = loyalty_settings_keyboard(settings)
    if chat_id and message_id:
        try:
            await message.bot.edit_message_text(
                text=text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup,
            )
            await state.update_data(
                loyalty_chat_id=chat_id,
                loyalty_message_id=message_id,
            )
            return
        except Exception:
            pass
    target = await message.answer(text, reply_markup=markup)
    await state.update_data(
        loyalty_chat_id=target.chat.id,
        loyalty_message_id=target.message_id,
    )


def _format_loyalty_settings_text(settings: ConfigService.LoyaltySettings) -> str:
    lines = [
        "<b>Loyalty & rewards</b>",
        f"Status: {'Enabled' if settings.enabled else 'Disabled'}",
        f"Earn rate: {settings.points_per_currency:.2f} pts per currency unit",
        f"Redeem ratio: {settings.redeem_ratio:.4f} currency per point",
        f"Minimum redeem: {settings.min_redeem_points} pts",
        f"Automatic earning: {'ON' if settings.auto_earn else 'OFF'}",
        f"Prompt users at checkout: {'ON' if settings.auto_prompt else 'OFF'}",
    ]
    if settings.redeem_ratio > 0:
        estimated_value = settings.redeem_ratio * max(settings.min_redeem_points, 1)
        lines.append(f"Estimated value of minimum redeem: {estimated_value:.2f}")
    return "\n".join(lines)


def _is_cancel(text: str) -> bool:
    return text.lower() in {"/cancel", "cancel", "abort"}
