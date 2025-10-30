from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.enums import CouponStatus, OrderStatus
from app.services.crypto_payment_service import OXAPAY_EXTRA_KEY

if TYPE_CHECKING:
    from app.services.config_service import ConfigService
    from app.infrastructure.db.models import Coupon, Order


class AdminMenuCallback(StrEnum):
    MANAGE_COUPONS = "admin:manage_coupons"
    TOGGLE_SUBSCRIPTION = "admin:toggle_subscription"
    MANAGE_CHANNELS = "admin:manage_channels"
    MANAGE_CRYPTO = "admin:manage_crypto"
    MANAGE_PAYMENTS = "admin:manage_payments"
    MANAGE_SUPPORT = "admin:manage_support"
    MANAGE_PRODUCTS = "admin:manage_products"
    MANAGE_USERS = "admin:manage_users"
    MANAGE_ORDERS = "admin:manage_orders"
    MANAGE_LOYALTY = "admin:manage_loyalty"
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


class AdminLoyaltyCallback(StrEnum):
    TOGGLE_ENABLED = "admin:loyalty:toggle_enabled"
    SET_EARN_RATE = "admin:loyalty:set_earn_rate"
    SET_REDEEM_RATIO = "admin:loyalty:set_redeem_ratio"
    SET_MIN_REDEEM = "admin:loyalty:set_min_redeem"
    TOGGLE_AUTO_EARN = "admin:loyalty:toggle_auto_earn"
    TOGGLE_AUTO_PROMPT = "admin:loyalty:toggle_auto_prompt"
    BACK = "admin:loyalty:back"


class AdminCouponCallback(StrEnum):
    CREATE = "admin:coupon:create"
    REFRESH = "admin:coupon:refresh"
    BACK = "admin:coupon:back"


ADMIN_ORDER_VIEW_PREFIX = "admin:orders:view:"
ADMIN_ORDER_MARK_FULFILLED_PREFIX = "admin:orders:mark_fulfilled:"
ADMIN_ORDER_MARK_PAID_PREFIX = "admin:orders:mark_paid:"
ADMIN_ORDER_RECEIPT_PREFIX = "admin:orders:receipt:"
ADMIN_ORDER_NOTIFY_DELIVERED_PREFIX = "admin:ord:delv:"
ADMIN_RECENT_ORDERS_PAGE_PREFIX = "admin:orders:recent_page:"
ADMIN_COUPON_VIEW_PREFIX = "admin:coupon:view:"
ADMIN_COUPON_TOGGLE_PREFIX = "admin:coupon:toggle:"
ADMIN_COUPON_EDIT_MENU_PREFIX = "admin:coupon:editmenu:"
ADMIN_COUPON_EDIT_FIELD_PREFIX = "admin:coupon:edit:"
ADMIN_COUPON_USAGE_PREFIX = "admin:coupon:usage:"
ADMIN_COUPON_DELETE_PREFIX = "admin:coupon:delete:"
ADMIN_COUPON_DELETE_CONFIRM_PREFIX = "admin:coupon:delete_confirm:"
ADMIN_COUPON_TOGGLE_AUTO_PREFIX = "admin:coupon:auto:"
ADMIN_COUPON_EDIT_TYPE_PREFIX = "admin:coupon:edit_type:"


def admin_menu_keyboard(subscription_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=("Disable subscription gate" if subscription_enabled else "Enable subscription gate"),
        callback_data=AdminMenuCallback.TOGGLE_SUBSCRIPTION.value,
    )
    builder.button(text="Required channels", callback_data=AdminMenuCallback.MANAGE_CHANNELS.value)
    builder.button(text="Crypto payments", callback_data=AdminMenuCallback.MANAGE_CRYPTO.value)
    builder.button(text="Payments dashboard", callback_data=AdminMenuCallback.MANAGE_PAYMENTS.value)
    builder.button(text="Support desk", callback_data=AdminMenuCallback.MANAGE_SUPPORT.value)
    builder.button(text="Products", callback_data=AdminMenuCallback.MANAGE_PRODUCTS.value)
    builder.button(text="Users", callback_data=AdminMenuCallback.MANAGE_USERS.value)
    builder.button(text="Orders", callback_data=AdminMenuCallback.MANAGE_ORDERS.value)
    builder.button(text="Coupons", callback_data=AdminMenuCallback.MANAGE_COUPONS.value)
    builder.button(text="Loyalty & rewards", callback_data=AdminMenuCallback.MANAGE_LOYALTY.value)
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


def loyalty_settings_keyboard(config: "ConfigService.LoyaltySettings") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Loyalty program: {'ON' if config.enabled else 'OFF'}",
        callback_data=AdminLoyaltyCallback.TOGGLE_ENABLED.value,
    )
    builder.button(
        text=f"Earn rate: {config.points_per_currency:.2f} pts / unit",
        callback_data=AdminLoyaltyCallback.SET_EARN_RATE.value,
    )
    builder.button(
        text=f"Redeem ratio: {config.redeem_ratio:.4f} currency / pt",
        callback_data=AdminLoyaltyCallback.SET_REDEEM_RATIO.value,
    )
    builder.button(
        text=f"Minimum redeem: {config.min_redeem_points} pts",
        callback_data=AdminLoyaltyCallback.SET_MIN_REDEEM.value,
    )
    builder.button(
        text=f"Auto-earn: {'ON' if config.auto_earn else 'OFF'}",
        callback_data=AdminLoyaltyCallback.TOGGLE_AUTO_EARN.value,
    )
    builder.button(
        text=f"Prompt users: {'ON' if config.auto_prompt else 'OFF'}",
        callback_data=AdminLoyaltyCallback.TOGGLE_AUTO_PROMPT.value,
    )
    builder.button(text="Back", callback_data=AdminLoyaltyCallback.BACK.value)
    builder.adjust(1)
    return builder.as_markup()


def coupon_dashboard_keyboard(coupons: Sequence["Coupon"]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Create coupon", callback_data=AdminCouponCallback.CREATE.value)
    for coupon in coupons:
        status = coupon.status.value.replace("_", " ").title()
        builder.button(
            text=f"{coupon.code} ({status})",
            callback_data=f"{ADMIN_COUPON_VIEW_PREFIX}{coupon.id}",
        )
    builder.button(text="Refresh list", callback_data=AdminCouponCallback.REFRESH.value)
    builder.button(text="Back", callback_data=AdminMenuCallback.BACK_TO_MAIN.value)
    builder.adjust(1)
    return builder.as_markup()


def coupon_details_keyboard(coupon: "Coupon") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = "Deactivate" if coupon.status == CouponStatus.ACTIVE else "Activate"
    builder.button(
        text=toggle_text,
        callback_data=f"{ADMIN_COUPON_TOGGLE_PREFIX}{coupon.id}",
    )
    builder.button(
        text=f"Auto-apply: {'ON' if getattr(coupon, 'auto_apply', False) else 'OFF'}",
        callback_data=f"{ADMIN_COUPON_TOGGLE_AUTO_PREFIX}{coupon.id}",
    )
    builder.button(
        text="Edit fields",
        callback_data=f"{ADMIN_COUPON_EDIT_MENU_PREFIX}{coupon.id}",
    )
    builder.button(
        text="Usage stats",
        callback_data=f"{ADMIN_COUPON_USAGE_PREFIX}{coupon.id}",
    )
    builder.button(
        text="Delete coupon",
        callback_data=f"{ADMIN_COUPON_DELETE_PREFIX}{coupon.id}",
    )
    builder.button(text="Back", callback_data=AdminCouponCallback.REFRESH.value)
    builder.adjust(1)
    return builder.as_markup()


def coupon_edit_keyboard(coupon: "Coupon") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Change name",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}name:{coupon.id}",
    )
    builder.button(
        text="Change description",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}description:{coupon.id}",
    )
    builder.button(
        text="Change type",
        callback_data=f"{ADMIN_COUPON_EDIT_TYPE_PREFIX}{coupon.id}",
    )
    builder.button(
        text="Change value",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}value:{coupon.id}",
    )
    builder.button(
        text="Set minimum order",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}min_total:{coupon.id}",
    )
    builder.button(
        text="Set max discount",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}max_discount:{coupon.id}",
    )
    builder.button(
        text="Set total limit",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}max_redemptions:{coupon.id}",
    )
    builder.button(
        text="Set per-user limit",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}per_user_limit:{coupon.id}",
    )
    builder.button(
        text="Set start date",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}start_at:{coupon.id}",
    )
    builder.button(
        text="Set end date",
        callback_data=f"{ADMIN_COUPON_EDIT_FIELD_PREFIX}end_at:{coupon.id}",
    )
    builder.button(
        text="Back to coupon",
        callback_data=f"{ADMIN_COUPON_VIEW_PREFIX}{coupon.id}",
    )
    builder.adjust(1)
    return builder.as_markup()


def coupon_usage_keyboard(coupon_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Refresh usage",
        callback_data=f"{ADMIN_COUPON_USAGE_PREFIX}{coupon_id}",
    )
    builder.button(
        text="Back to coupon",
        callback_data=f"{ADMIN_COUPON_VIEW_PREFIX}{coupon_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


def coupon_delete_confirm_keyboard(coupon_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Yes, delete",
        callback_data=f"{ADMIN_COUPON_DELETE_CONFIRM_PREFIX}{coupon_id}",
    )
    builder.button(
        text="Back to coupon",
        callback_data=f"{ADMIN_COUPON_VIEW_PREFIX}{coupon_id}",
    )
    builder.adjust(1)
    return builder.as_markup()


def recent_orders_keyboard(
    orders: Sequence["Order"],
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        status = order.status.value.replace("_", " ").title()
        amount = f"{order.total_amount} {order.currency}"
        builder.button(
            text=f"{status} • {amount}",
            callback_data=f"{ADMIN_ORDER_VIEW_PREFIX}{order.public_id}",
        )
    nav_buttons: list[InlineKeyboardButton] = []
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"{ADMIN_RECENT_ORDERS_PAGE_PREFIX}{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text="Refresh",
            callback_data=f"{ADMIN_RECENT_ORDERS_PAGE_PREFIX}{page}",
        )
    )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️ Next",
                callback_data=f"{ADMIN_RECENT_ORDERS_PAGE_PREFIX}{page + 1}",
            )
        )
    builder.row(*nav_buttons)
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
    if order.status == OrderStatus.PAID and not _fulfillment_recorded(order):
        builder.button(
            text="Mark fulfilled",
            callback_data=f"{ADMIN_ORDER_MARK_FULFILLED_PREFIX}{order.public_id}",
        )
    if order.status == OrderStatus.PAID and not _delivery_notice_sent(order):
        builder.button(
            text="Notify delivered",
            callback_data=f"{ADMIN_ORDER_NOTIFY_DELIVERED_PREFIX}{order.public_id}",
        )
    if order.status == OrderStatus.PAID:
        builder.button(
            text="Send receipt",
            callback_data=f"{ADMIN_ORDER_RECEIPT_PREFIX}{order.public_id}",
        )
    builder.button(text="Back to orders", callback_data=AdminOrderCallback.VIEW_RECENT.value)
    builder.adjust(1)
    return builder.as_markup()


def _oxapay_meta(order: "Order") -> dict:
    extra = order.extra_attrs or {}
    meta = extra.get(OXAPAY_EXTRA_KEY)
    return meta if isinstance(meta, dict) else {}


def _fulfillment_recorded(order: "Order") -> bool:
    fulfillment = _oxapay_meta(order).get("fulfillment")
    return isinstance(fulfillment, dict) and bool(fulfillment.get("delivered_at"))


def _delivery_notice_sent(order: "Order") -> bool:
    delivery = _oxapay_meta(order).get("delivery_notice")
    return isinstance(delivery, dict) and bool(delivery.get("sent_at"))
