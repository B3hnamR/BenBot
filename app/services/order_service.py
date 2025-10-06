from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order, Product
from app.infrastructure.db.repositories import OrderRepository, ProductRepository


class OrderCreationError(RuntimeError):
    """Raised when an order cannot be created."""


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._products = ProductRepository(session)

    async def get_product(self, product_id: int) -> Product | None:
        return await self._products.get_by_id(product_id)

    async def list_user_orders(self, user_id: int) -> list[Order]:
        return await self._orders.list_for_user(user_id)

    async def get_order_by_public_id(self, public_id: str) -> Order | None:
        return await self._orders.get_by_public_id(public_id)

    async def create_order(
        self,
        *,
        user_id: int,
        product: Product,
        answers: Iterable[tuple[str, str | None]],
        invoice_timeout_minutes: int,
    ) -> Order:
        if not product.is_active:
            raise OrderCreationError("Product is not active.")

        expires_at: datetime | None = None
        if invoice_timeout_minutes > 0:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(
                minutes=invoice_timeout_minutes
            )

        order = await self._orders.create_order(
            user_id=user_id,
            product_id=product.id,
            amount=Decimal(product.price),
            currency=product.currency,
            expires_at=expires_at,
            extra_attrs=None,
        )
        order.status = OrderStatus.AWAITING_PAYMENT

        for key, value in answers:
            await self._orders.add_answer(order, question_key=key, answer_text=value)

        await self._session.flush()
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
        return order

    async def mark_cancelled(self, order: Order) -> Order:
        order.status = OrderStatus.CANCELLED
        return order

    async def mark_paid(self, order: Order, charge_id: str) -> Order:
        return await self._orders.mark_paid(order, charge_id=charge_id)

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
