from __future__ import annotations

from enum import IntEnum, StrEnum


class SettingKey(StrEnum):
    SUBSCRIPTION_REQUIRED = "subscription.required"
    SUBSCRIPTION_CHANNELS = "subscription.channels"
    PAYMENT_PROVIDER_TOKEN = "payment.provider_token"
    PAYMENT_CURRENCY = "payment.currency"
    INVOICE_TIMEOUT_MINUTES = "payment.invoice_timeout_minutes"
    PAYMENT_CRYPTO_ENABLED = "payment.crypto.enabled"
    PAYMENT_CRYPTO_ALLOWED_CURRENCIES = "payment.crypto.allowed_currencies"
    PAYMENT_CRYPTO_LIFETIME_MINUTES = "payment.crypto.lifetime_minutes"
    PAYMENT_CRYPTO_MIXED_PAYMENT = "payment.crypto.mixed_payment"
    PAYMENT_CRYPTO_FEE_PAYER = "payment.crypto.fee_payer"
    PAYMENT_CRYPTO_UNDERPAID_COVERAGE = "payment.crypto.underpaid_coverage"
    PAYMENT_CRYPTO_AUTO_WITHDRAWAL = "payment.crypto.auto_withdrawal"
    PAYMENT_CRYPTO_TO_CURRENCY = "payment.crypto.to_currency"
    PAYMENT_CRYPTO_RETURN_URL = "payment.crypto.return_url"
    PAYMENT_CRYPTO_CALLBACK_URL = "payment.crypto.callback_url"
    PAYMENT_CRYPTO_CALLBACK_SECRET = "payment.crypto.callback_secret"
    ALERT_ORDER_PAYMENT = "alerts.order.payment"
    ALERT_ORDER_CANCELLED = "alerts.order.cancelled"
    ALERT_ORDER_EXPIRED = "alerts.order.expired"
    SUPPORT_ANTISPAM_MAX_OPEN_TICKETS = "support.antispam.max_open_tickets"
    SUPPORT_ANTISPAM_MAX_TICKETS_PER_WINDOW = "support.antispam.max_tickets_per_window"
    SUPPORT_ANTISPAM_WINDOW_MINUTES = "support.antispam.window_minutes"
    SUPPORT_ANTISPAM_MIN_REPLY_INTERVAL_SECONDS = "support.antispam.min_reply_interval_seconds"


class OrderStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_PAYMENT = "awaiting_payment"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ProductQuestionType(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    PHONE = "phone"
    NUMBER = "number"
    SELECT = "select"
    MULTISELECT = "multiselect"


class MembershipStatus(IntEnum):
    UNKNOWN = 0
    MEMBER = 1
    NOT_MEMBER = 2


class SupportTicketStatus(StrEnum):
    OPEN = "open"
    AWAITING_USER = "awaiting_user"
    AWAITING_ADMIN = "awaiting_admin"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class SupportTicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SupportAuthorRole(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
