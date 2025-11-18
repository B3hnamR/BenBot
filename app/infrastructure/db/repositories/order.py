from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order, OrderAnswer, Product

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

    async def list_for_user(self, user_id: int) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.answers),
                selectinload(Order.product),
            )
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars().unique().all())

    async def get_by_id(self, order_id: int) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.user),
                joinedload(Order.product),
                joinedload(Order.answers),
            )
            .where(Order.id == order_id)
        )
        return result.unique().scalar_one_or_none()

    async def paginate_user_orders(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[Order], bool]:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.answers),
                selectinload(Order.product),
            )
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        orders = list(result.scalars().unique().all())
        has_more = len(orders) > limit
        return orders[:limit], has_more

    async def get_by_public_id(self, public_id: str) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.answers),
                joinedload(Order.product),
                joinedload(Order.user),
            )
            .where(Order.public_id == public_id)
        )
        return result.unique().scalar_one_or_none()

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

    async def merge_extra_attrs(self, order: Order, updates: dict) -> Order:
        extra = dict(order.extra_attrs or {})
        extra.update(updates)
        order.extra_attrs = extra
        return order

    async def get_by_invoice_payload(self, payload: str) -> Order | None:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.answers),
                joinedload(Order.product),
                joinedload(Order.user),
            )
            .where(Order.invoice_payload == payload)
        )
        return result.unique().scalar_one_or_none()

    async def list_pending_crypto(self, limit: int = 10) -> list[Order]:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.answers),
                joinedload(Order.user),
                joinedload(Order.product),
            )
            .where(
                Order.status == OrderStatus.AWAITING_PAYMENT,
                Order.invoice_payload.isnot(None),
            )
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def crypto_status_counts(self) -> dict[OrderStatus, int]:
        result = await self.session.execute(
            select(Order.status, func.count())
            .where(Order.invoice_payload.isnot(None))
            .group_by(Order.status)
        )
        return {status: count for status, count in result.all()}

    async def list_recent(self, limit: int = 10) -> list[Order]:
        orders, _ = await self.paginate_recent(limit=limit, offset=0)
        return orders

    async def paginate_recent(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[Order], bool]:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.answers),
                joinedload(Order.user),
                joinedload(Order.product),
            )
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        orders = list(result.scalars().unique().all())
        has_more = len(orders) > limit
        return orders[:limit], has_more

    async def payment_status_summary(self) -> dict[OrderStatus, dict[str, dict[str, Decimal | int]]]:
        result = await self.session.execute(
            select(
                Order.status,
                Order.currency,
                func.count(),
                func.coalesce(func.sum(Order.total_amount), 0),
            )
            .group_by(Order.status, Order.currency)
        )
        summary: dict[OrderStatus, dict[str, dict[str, Decimal | int]]] = {}
        for status, currency, count, total in result:
            status_map = summary.setdefault(status, {})
            status_map[currency] = {
                "count": int(count),
                "total": Decimal(total or 0),
            }
        return summary

    async def paginate_recent_paid(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[Order], bool]:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.user),
                joinedload(Order.product),
            )
            .where(Order.status == OrderStatus.PAID)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        orders = list(result.scalars().unique().all())
        has_more = len(orders) > limit
        return orders[:limit], has_more

    async def list_recent_paid(self, limit: int = 5) -> list[Order]:
        orders, _ = await self.paginate_recent_paid(limit=limit, offset=0)
        return orders

    async def paginate_pending_payments(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[Order], bool]:
        result = await self.session.execute(
            select(Order)
            .options(
                joinedload(Order.user),
                joinedload(Order.product),
            )
            .where(Order.status == OrderStatus.AWAITING_PAYMENT)
            .order_by(Order.payment_expires_at.asc(), Order.created_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        orders = list(result.scalars().unique().all())
        has_more = len(orders) > limit
        return orders[:limit], has_more

    async def list_pending_payments(self, limit: int = 10) -> list[Order]:
        orders, _ = await self.paginate_pending_payments(limit=limit, offset=0)
        return orders

    async def search_orders(self, query: str, *, limit: int = 20) -> list[Order]:
        if not query:
            return []
        like = f"%{query.lower()}%"
        predicates = [
            func.lower(Order.public_id).like(like),
            func.lower(func.coalesce(Order.invoice_payload, "")).like(like),
            func.lower(func.coalesce(Product.name, "")).like(like),
        ]
        if query.isdigit():
            predicates.append(Order.user_id == int(query))
            predicates.append(Order.id == int(query))
        stmt = (
            select(Order)
            .join(Product, Product.id == Order.product_id)
            .options(
                joinedload(Order.user),
                joinedload(Order.product),
            )
            .where(or_(*predicates))
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def top_paid_products(self, limit: int = 5) -> list[tuple[str, str, int, Decimal]]:
        result = await self.session.execute(
            select(
                Product.name,
                Order.currency,
                func.count(),
                func.coalesce(func.sum(Order.total_amount), 0),
            )
            .join(Product, Product.id == Order.product_id)
            .where(Order.status == OrderStatus.PAID)
            .group_by(Product.id, Product.name, Order.currency)
            .order_by(func.coalesce(func.sum(Order.total_amount), 0).desc())
            .limit(limit)
        )
        return [
            (
                name,
                currency,
                int(count),
                Decimal(total or 0),
            )
            for name, currency, count, total in result.all()
        ]
