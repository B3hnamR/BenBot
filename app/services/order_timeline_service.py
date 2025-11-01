from __future__ import annotations

from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Order, OrderTimeline
from app.infrastructure.db.repositories.order_timeline import OrderTimelineRepository


class OrderTimelineService:
    DEFAULT_LABELS: dict[str, str] = {
        "created": "Order created",
        "awaiting_payment": "Awaiting payment",
        "paid": "Payment confirmed",
        "processing": "Processing",
        "shipping": "Shipped",
        "delivered": "Delivered",
        "cancelled": "Order cancelled",
        "expired": "Order expired",
        "reopened": "Payment window reopened",
        "note": "Note",
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = OrderTimelineRepository(session)

    async def add_event(
        self,
        order: Order | int,
        *,
        status: str | None = None,
        note: str | None = None,
        actor: str | None = None,
        event_type: str = "status",
        meta: dict | None = None,
    ) -> OrderTimeline:
        order_id = order.id if isinstance(order, Order) else int(order)
        return await self._repo.add_event(
            order_id,
            event_type=event_type,
            status=status,
            note=note,
            actor=actor,
            meta=meta,
        )

    async def list_events(self, order: Order | int) -> list[OrderTimeline]:
        order_id = order.id if isinstance(order, Order) else int(order)
        return await self._repo.list_for_order(order_id)

    @classmethod
    def label_for_status(cls, status: str | None) -> str:
        if not status:
            return "Update"
        return cls.DEFAULT_LABELS.get(status, status.replace("_", " ").title())
