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
