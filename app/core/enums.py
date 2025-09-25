from __future__ import annotations

from enum import IntEnum, StrEnum


class SettingKey(StrEnum):
    SUBSCRIPTION_REQUIRED = "subscription.required"
    SUBSCRIPTION_CHANNELS = "subscription.channels"
    PAYMENT_PROVIDER_TOKEN = "payment.provider_token"
    PAYMENT_CURRENCY = "payment.currency"
    INVOICE_TIMEOUT_MINUTES = "payment.invoice_timeout_minutes"


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
