from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order, Product
from app.infrastructure.db.repositories import OrderRepository, ProductRepository
from app.services.order_duration_service import OrderDurationService
from app.services.order_timeline_service import OrderTimelineService


class OrderCreationError(RuntimeError):
    """Raised when an order cannot be created."""


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._products = ProductRepository(session)
        self._timeline = OrderTimelineService(session)
        self._duration = OrderDurationService(session)

    async def get_product(self, product_id: int) -> Product | None:
        return await self._products.get_by_id(product_id)

    async def list_user_orders(self, user_id: int) -> list[Order]:
        return await self._orders.list_for_user(user_id)

    async def paginate_user_orders(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[Order], bool]:
        return await self._orders.paginate_user_orders(user_id, limit=limit, offset=offset)

    async def get_order_by_public_id(self, public_id: str) -> Order | None:
        return await self._orders.get_by_public_id(public_id)

    async def create_order(
        self,
        *,
        user_id: int,
        product: Product,
        answers: Iterable[tuple[str, str | None]],
        invoice_timeout_minutes: int,
        total_override: Decimal | None = None,
        currency_override: str | None = None,
        extra_attrs: dict | None = None,
    ) -> Order:
        if not product.is_active:
            raise OrderCreationError("Product is not active.")

        expires_at: datetime | None = None
        if invoice_timeout_minutes > 0:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(
                minutes=invoice_timeout_minutes
            )

        amount = total_override if total_override is not None else Decimal(product.price)
        currency = currency_override if currency_override is not None else product.currency

        order = await self._orders.create_order(
            user_id=user_id,
            product_id=product.id,
            amount=amount,
            currency=currency,
            expires_at=expires_at,
            extra_attrs=extra_attrs,
        )
        order.status = OrderStatus.AWAITING_PAYMENT
        await self._duration.start(order, duration_days=getattr(product, "service_duration_days", None))

        for key, value in answers:
            await self._orders.add_answer(order, question_key=key, answer_text=value)

        await self._session.flush()
        await self._timeline.add_event(
            order,
            status="created",
            note="Order created",
            actor="system",
        )
        await self._timeline.add_event(
            order,
            status="awaiting_payment",
            note="Invoice issued",
            actor="system",
        )
        return order

    async def enforce_expiration(self, order: Order) -> Order:
        if order.status != OrderStatus.AWAITING_PAYMENT:
            return order

        expires_at = order.payment_expires_at
        if expires_at is None:
            return order

        aware_expires_at = self._ensure_utc(expires_at)
        if aware_expires_at <= datetime.now(tz=timezone.utc):
            order.status = OrderStatus.EXPIRED
            await self._timeline.add_event(
                order,
                status="expired",
                note="Invoice expired",
                actor="system",
            )
        return order

    async def mark_cancelled(self, order: Order, *, actor: str | None = None) -> Order:
        order.status = OrderStatus.CANCELLED
        await self._timeline.add_event(
            order,
            status="cancelled",
            note="Order cancelled",
            actor=actor or "system",
        )
        return order

    async def mark_paid(self, order: Order, charge_id: str, *, actor: str | None = None) -> Order:
        result = await self._orders.mark_paid(order, charge_id=charge_id)
        await self._timeline.add_event(
            order,
            status="paid",
            note="Payment received",
            actor=actor or "system",
        )
        return result

    async def reopen_for_payment(
        self,
        order: Order,
        *,
        invoice_timeout_minutes: int,
        actor: str | None = None,
    ) -> Order:
        if order.product is None:
            await self._session.refresh(order, attribute_names=["product"])

        product = order.product
        if product is not None and not product.is_active:
            raise OrderCreationError("Product is not active.")

        expires_at: datetime | None = None
        if invoice_timeout_minutes > 0:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(
                minutes=invoice_timeout_minutes
            )

        order.status = OrderStatus.AWAITING_PAYMENT
        order.payment_provider = None
        order.payment_charge_id = None
        order.invoice_payload = None
        order.payment_expires_at = expires_at

        await self._session.flush()
        await self._timeline.add_event(
            order,
            status="awaiting_payment",
            note="Invoice reissued",
            actor=actor or "system",
        )
        return order


    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
