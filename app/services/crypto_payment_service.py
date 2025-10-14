from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories import OrderRepository
from app.services.config_service import ConfigService
from app.services.oxapay_client import OxapayClient, OxapayError, OxapayInvoice, OxapayPayment

OXAPAY_EXTRA_KEY = "oxapay_payment"


@dataclass
class CryptoInvoiceResult:
    enabled: bool
    pay_link: str | None = None
    track_id: str | None = None
    status: str | None = None
    expires_at: datetime | None = None
    raw: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class CryptoSyncResult:
    updated: bool
    status: str | None
    order_status: OrderStatus
    pay_link: str | None
    expires_at: datetime | None
    raw: dict[str, Any] | None = None
    error: str | None = None


class CryptoPaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._config_service = ConfigService(session)
        self._settings = get_settings()

    async def create_invoice_for_order(
        self,
        order: Order,
        *,
        description: str | None = None,
        email: str | None = None,
    ) -> CryptoInvoiceResult:
        if not self._settings.oxapay_api_key:
            return CryptoInvoiceResult(enabled=False, error="OxaPay API key is not configured.")

        crypto_config = await self._config_service.get_crypto_settings()
        if not crypto_config.enabled:
            return CryptoInvoiceResult(enabled=False, error="Crypto payments are disabled.")

        try:
            client = self._get_client()
        except ValueError as exc:
            return CryptoInvoiceResult(enabled=False, error=str(exc))

        payload = self._build_invoice_payload(order, crypto_config, description=description, email=email)
        try:
            invoice: OxapayInvoice = await client.create_invoice(payload)
        except OxapayError as exc:
            await self._orders.merge_extra_attrs(
                order,
                {
                    OXAPAY_EXTRA_KEY: {
                        "error": str(exc),
                        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                    }
                },
            )
            return CryptoInvoiceResult(
                enabled=True,
                error=str(exc),
            )

        if not invoice.track_id:
            await self._orders.merge_extra_attrs(
                order,
                {
                    OXAPAY_EXTRA_KEY: {
                        "error": "Missing track ID in invoice response.",
                        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                        "raw": invoice.data,
                    }
                },
            )
            return CryptoInvoiceResult(enabled=True, error="OxaPay did not return a track ID for the invoice.")

        expires_at = invoice.expires_at or self._estimated_expiry(crypto_config.lifetime_minutes)
        await self._orders.set_invoice_details(
            order,
            provider="oxapay",
            payload=str(invoice.track_id),
            expires_at=expires_at,
        )
        await self._orders.merge_extra_attrs(
            order,
            {
                OXAPAY_EXTRA_KEY: {
                    "track_id": invoice.track_id,
                    "pay_link": invoice.pay_link,
                    "status": invoice.status,
                    "amount": invoice.amount,
                    "currency": invoice.currency,
                    "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                    "raw": invoice.data,
                }
            },
        )
        return CryptoInvoiceResult(
            enabled=True,
            pay_link=invoice.pay_link,
            track_id=invoice.track_id,
            status=invoice.status,
            expires_at=expires_at,
            raw=invoice.data,
        )

    async def refresh_order_status(self, order: Order) -> CryptoSyncResult:
        track_id = (order.invoice_payload or "").strip()
        if not track_id:
            return CryptoSyncResult(
                updated=False,
                status=None,
                order_status=order.status,
                pay_link=self._current_pay_link(order),
                expires_at=order.payment_expires_at,
            )

        if not self._settings.oxapay_api_key:
            return CryptoSyncResult(
                updated=False,
                status=None,
                order_status=order.status,
                pay_link=self._current_pay_link(order),
                expires_at=order.payment_expires_at,
                error="OxaPay API key is not configured.",
            )

        try:
            client = self._get_client()
        except ValueError as exc:
            return CryptoSyncResult(
                updated=False,
                status=None,
                order_status=order.status,
                pay_link=self._current_pay_link(order),
                expires_at=order.payment_expires_at,
                error=str(exc),
            )

        try:
            payment: OxapayPayment = await client.get_payment(track_id)
        except OxapayError as exc:
            return CryptoSyncResult(
                updated=False,
                status=None,
                order_status=order.status,
                pay_link=self._current_pay_link(order),
                expires_at=order.payment_expires_at,
                error=str(exc),
            )

        pay_link = (
            payment.data.get("pay_link")
            or payment.data.get("payment_url")
            or payment.data.get("link")
            or self._current_pay_link(order)
        )
        new_status = self._map_oxapay_status(payment.status)
        updated = new_status != order.status
        if new_status == OrderStatus.PAID:
            charge_id = self._extract_charge_id(payment)
            await self._orders.mark_paid(order, charge_id=charge_id or track_id, paid_at=datetime.now(tz=timezone.utc))
        elif new_status == OrderStatus.EXPIRED:
            await self._orders.set_status(order, OrderStatus.EXPIRED)
            pay_link = None
        elif new_status == OrderStatus.CANCELLED:
            await self._orders.set_status(order, OrderStatus.CANCELLED)
            pay_link = None
        else:
            # Keep awaiting payment but update expiry timestamp.
            if payment.expired_at:
                order.payment_expires_at = payment.expired_at

        if order.status != OrderStatus.AWAITING_PAYMENT:
            pay_link = None

        await self._orders.merge_extra_attrs(
            order,
            {
                OXAPAY_EXTRA_KEY: {
                    "track_id": payment.track_id,
                    "pay_link": pay_link,
                    "status": payment.status,
                    "updated_at": datetime.now(tz=timezone.utc).isoformat(),
                    "raw": payment.data,
                }
            },
        )

        return CryptoSyncResult(
            updated=updated,
            status=payment.status,
            order_status=order.status,
            pay_link=pay_link,
            expires_at=order.payment_expires_at or payment.expired_at,
            raw=payment.data,
        )

    async def list_accepted_currencies(self) -> list[str]:
        if not self._settings.oxapay_api_key:
            return []
        client = self._get_client()
        try:
            return await client.get_accepted_currencies()
        except OxapayError:
            return []

    async def invalidate_invoice(self, order: Order, reason: str = "cancelled") -> None:
        existing = (order.extra_attrs or {}).get(OXAPAY_EXTRA_KEY) or {}
        existing.update(
            {
                "status": reason,
                "pay_link": None,
                "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
        await self._orders.merge_extra_attrs(order, {OXAPAY_EXTRA_KEY: existing})
        order.invoice_payload = None
        order.payment_provider = None
        order.payment_expires_at = None

    def _get_client(self) -> OxapayClient:
        return OxapayClient(
            api_key=self._settings.oxapay_api_key or "",
            base_url=self._settings.oxapay_base_url,
            timeout=15.0,
        )

    def _build_invoice_payload(
        self,
        order: Order,
        crypto_config: ConfigService.CryptoSettings,
        *,
        description: str | None,
        email: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "amount": self._decimal_to_number(order.total_amount),
            "currency": order.currency,
            "lifetime": max(15, min(crypto_config.lifetime_minutes, 2880)),
            "mixed_payment": crypto_config.mixed_payment,
            "sandbox": self._settings.oxapay_sandbox,
            "order_id": order.public_id,
        }

        if crypto_config.fee_payer == "payer":
            payload["fee_paid_by_payer"] = 1
        else:
            payload["fee_paid_by_payer"] = 0

        coverage = max(0.0, min(crypto_config.underpaid_coverage, 60.0))
        if coverage:
            payload["under_paid_coverage"] = coverage
        payload["auto_withdrawal"] = crypto_config.auto_withdrawal

        if crypto_config.to_currency:
            payload["to_currency"] = crypto_config.to_currency
        if crypto_config.return_url:
            payload["return_url"] = crypto_config.return_url
        if crypto_config.callback_url:
            payload["callback_url"] = crypto_config.callback_url
        if email:
            payload["email"] = email
        if description:
            payload["description"] = description

        return payload

    @staticmethod
    def _decimal_to_number(value: Decimal) -> float:
        return float(value)

    @staticmethod
    def _estimated_expiry(minutes: int) -> datetime:
        minutes = max(1, minutes)
        return datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)

    @staticmethod
    def _map_oxapay_status(status: str | None) -> OrderStatus:
        if not status:
            return OrderStatus.AWAITING_PAYMENT
        normalized = status.lower()
        if normalized in {"paid", "manual_accept"}:
            return OrderStatus.PAID
        if normalized in {"expired"}:
            return OrderStatus.EXPIRED
        if normalized in {"refunded", "refunding"}:
            return OrderStatus.CANCELLED
        return OrderStatus.AWAITING_PAYMENT

    @staticmethod
    def _extract_charge_id(payment: OxapayPayment) -> str | None:
        for tx in payment.transactions:
            tx_hash = tx.get("tx_hash")
            if tx_hash:
                return str(tx_hash)
        return None

    def _current_pay_link(self, order: Order) -> str | None:
        data = (order.extra_attrs or {}).get(OXAPAY_EXTRA_KEY) or {}
        return data.get("pay_link")
