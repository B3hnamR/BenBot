from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.enums import OrderStatus

if TYPE_CHECKING:
    from app.services.config_service import ConfigService
    from app.infrastructure.db.models import Order


class AdminMenuCallback(StrEnum):
    TOGGLE_SUBSCRIPTION = "admin:toggle_subscription"
    MANAGE_CHANNELS = "admin:manage_channels"
    MANAGE_CRYPTO = "admin:manage_crypto"
    MANAGE_PRODUCTS = "admin:manage_products"
    MANAGE_USERS = "admin:manage_users"
    MANAGE_ORDERS = "admin:manage_orders"
    BACK_TO_MAIN = "admin:back_to_main"


class AdminCryptoCallback(StrEnum):
    TOGGLE_ENABLED = "admin:crypto:toggle_enabled"
    TOGGLE_MIXED = "admin:crypto:toggle_mixed"
    TOGGLE_FEE_PAYER = "admin:crypto:toggle_fee_payer"
    TOGGLE_AUTO_WITHDRAWAL = "admin:crypto:toggle_auto_withdrawal"
    SET_CURRENCIES = "admin:crypto:set_currencies"
    SET_LIFETIME = "admin:crypto:set_lifetime"
    SET_UNDERPAID = "admin:crypto:set_underpaid"
    SET_TO_CURRENCY = "admin:crypto:set_to_currency"
    SET_RETURN_URL = "admin:crypto:set_return_url"
    SET_CALLBACK_URL = "admin:crypto:set_callback_url"
    SET_CALLBACK_SECRET = "admin:crypto:set_callback_secret"
    REFRESH_ACCEPTED = "admin:crypto:refresh"
    VIEW_PENDING = "admin:crypto:view_pending"
    SYNC_PENDING = "admin:crypto:sync_pending"
    BACK = "admin:crypto:back"


class AdminOrderCallback(StrEnum):
    TOGGLE_PAYMENT_ALERT = "admin:orders:toggle_payment"
    TOGGLE_CANCEL_ALERT = "admin:orders:toggle_cancel"
    TOGGLE_EXPIRE_ALERT = "admin:orders:toggle_expire"
    VIEW_RECENT = "admin:orders:view_recent"
    BACK = "admin:orders:back"


ADMIN_ORDER_VIEW_PREFIX = "admin:orders:view:"
ADMIN_ORDER_MARK_FULFILLED_PREFIX = "admin:orders:mark_fulfilled:"
ADMIN_ORDER_MARK_PAID_PREFIX = "admin:orders:mark_paid:"
ADMIN_ORDER_RECEIPT_PREFIX = "admin:orders:receipt:"


def admin_menu_keyboard(subscription_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=("Disable subscription gate" if subscription_enabled else "Enable subscription gate"),
        callback_data=AdminMenuCallback.TOGGLE_SUBSCRIPTION.value,
    )
    builder.button(text="Required channels", callback_data=AdminMenuCallback.MANAGE_CHANNELS.value)
    builder.button(text="Crypto payments", callback_data=AdminMenuCallback.MANAGE_CRYPTO.value)
    builder.button(text="Products", callback_data=AdminMenuCallback.MANAGE_PRODUCTS.value)
    builder.button(text="Users", callback_data=AdminMenuCallback.MANAGE_USERS.value)
    builder.button(text="Orders", callback_data=AdminMenuCallback.MANAGE_ORDERS.value)
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def admin_channels_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Add channel", callback_data="admin:channel:add")
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def crypto_settings_keyboard(config: "ConfigService.CryptoSettings") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=("Disable crypto payments" if config.enabled else "Enable crypto payments"),
        callback_data=AdminCryptoCallback.TOGGLE_ENABLED.value,
    )
    builder.button(
        text=(f"Mixed payment: {'ON' if config.mixed_payment else 'OFF'}"),
        callback_data=AdminCryptoCallback.TOGGLE_MIXED.value,
    )
    fee_label = "Fee payer: Customer" if config.fee_payer == "payer" else "Fee payer: Merchant"
    builder.button(
        text=fee_label,
        callback_data=AdminCryptoCallback.TOGGLE_FEE_PAYER.value,
    )
    builder.button(
        text=(f"Auto withdrawal: {'ON' if config.auto_withdrawal else 'OFF'}"),
        callback_data=AdminCryptoCallback.TOGGLE_AUTO_WITHDRAWAL.value,
    )
    builder.button(
        text="Set allowed currencies",
        callback_data=AdminCryptoCallback.SET_CURRENCIES.value,
    )
    builder.button(
        text="Set invoice lifetime",
        callback_data=AdminCryptoCallback.SET_LIFETIME.value,
    )
    builder.button(
        text="Set underpaid coverage",
        callback_data=AdminCryptoCallback.SET_UNDERPAID.value,
    )
    builder.button(
        text="Set settlement currency",
        callback_data=AdminCryptoCallback.SET_TO_CURRENCY.value,
    )
    builder.button(
        text="Set return URL",
        callback_data=AdminCryptoCallback.SET_RETURN_URL.value,
    )
    builder.button(
        text="Set callback URL",
        callback_data=AdminCryptoCallback.SET_CALLBACK_URL.value,
    )
    builder.button(
        text="Set callback secret",
        callback_data=AdminCryptoCallback.SET_CALLBACK_SECRET.value,
    )
    builder.button(
        text="Show supported currencies",
        callback_data=AdminCryptoCallback.REFRESH_ACCEPTED.value,
    )
    builder.button(
        text="View open invoices",
        callback_data=AdminCryptoCallback.VIEW_PENDING.value,
    )
    builder.button(
        text="Sync open invoices",
        callback_data=AdminCryptoCallback.SYNC_PENDING.value,
    )
    builder.button(text="Back", callback_data=AdminCryptoCallback.BACK.value)
    builder.adjust(1)
    return builder.as_markup()


def order_settings_keyboard(config: "ConfigService.AlertSettings") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Payment alerts: {'ON' if config.notify_payment else 'OFF'}",
        callback_data=AdminOrderCallback.TOGGLE_PAYMENT_ALERT.value,
    )
    builder.button(
        text=f"Cancellation alerts: {'ON' if config.notify_cancellation else 'OFF'}",
        callback_data=AdminOrderCallback.TOGGLE_CANCEL_ALERT.value,
    )
    builder.button(
        text=f"Expiration alerts: {'ON' if config.notify_expiration else 'OFF'}",
        callback_data=AdminOrderCallback.TOGGLE_EXPIRE_ALERT.value,
    )
    builder.button(
        text="Review recent orders",
        callback_data=AdminOrderCallback.VIEW_RECENT.value,
    )
    builder.button(text="Back", callback_data=AdminOrderCallback.BACK.value)
    builder.adjust(1)
    return builder.as_markup()


def recent_orders_keyboard(orders: Sequence["Order"]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        status = order.status.value.replace("_", " ").title()
        amount = f"{order.total_amount} {order.currency}"
        builder.button(
            text=f"{status} • {amount}",
            callback_data=f"{ADMIN_ORDER_VIEW_PREFIX}{order.public_id}",
        )
    builder.button(text="Back", callback_data=AdminOrderCallback.BACK.value)
    builder.adjust(1)
    return builder.as_markup()


def order_manage_keyboard(order: "Order") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if order.status in {OrderStatus.AWAITING_PAYMENT, OrderStatus.CANCELLED, OrderStatus.EXPIRED}:
        builder.button(
            text="Mark as paid",
            callback_data=f"{ADMIN_ORDER_MARK_PAID_PREFIX}{order.public_id}",
        )
    if order.status == OrderStatus.PAID:
        builder.button(
            text="Mark fulfilled",
            callback_data=f"{ADMIN_ORDER_MARK_FULFILLED_PREFIX}{order.public_id}",
        )
        builder.button(
            text="Send receipt",
            callback_data=f"{ADMIN_ORDER_RECEIPT_PREFIX}{order.public_id}",
        )
    builder.button(text="Back to orders", callback_data=AdminOrderCallback.VIEW_RECENT.value)
    builder.adjust(1)
    return builder.as_markup()
