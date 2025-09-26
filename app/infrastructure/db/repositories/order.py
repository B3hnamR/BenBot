from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order, OrderAnswer

from .base import BaseRepository


class OrderRepository(BaseRepository):
    async def create_order(
        self,
        user_id: int,
        product_id: int,
        amount: Decimal,
        currency: str,
        expires_at: datetime | None,
        extra_attrs: dict | None = None,
    ) -> Order:
        order = Order(
            public_id=str(uuid4()),
            user_id=user_id,
            product_id=product_id,
            total_amount=amount,
            currency=currency,
            status=OrderStatus.DRAFT,
            payment_expires_at=expires_at,
            extra_attrs=extra_attrs,
        )
        await self.add(order)
        return order

    async def add_answer(
        self,
        order: Order,
        question_key: str,
        answer_text: str | None,
        extra_data: dict | None = None,
    ) -> OrderAnswer:
        answer = OrderAnswer(
            order=order,
            question_key=question_key,
            answer_text=answer_text,
            extra_data=extra_data,
        )
        await self.add(answer)
        return answer

    async def get_by_public_id(self, public_id: str) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(joinedload(Order.answers))
            .where(Order.public_id == public_id)
        )
        return result.scalar_one_or_none()

    async def set_status(self, order: Order, status: OrderStatus) -> Order:
        order.status = status
        return order

    async def set_invoice_details(
        self,
        order: Order,
        provider: str,
        payload: str,
        expires_at: datetime | None,
    ) -> Order:
        order.payment_provider = provider
        order.invoice_payload = payload
        order.payment_expires_at = expires_at
        return order

    async def mark_paid(
        self,
        order: Order,
        charge_id: str,
        paid_at: datetime | None = None,
    ) -> Order:
        order.status = OrderStatus.PAID
        order.payment_charge_id = charge_id
        order.payment_expires_at = paid_at
        return order
