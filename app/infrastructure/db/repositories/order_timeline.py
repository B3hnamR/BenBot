from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.infrastructure.db.models import OrderTimeline

from .base import BaseRepository


class OrderTimelineRepository(BaseRepository):
    async def add_event(
        self,
        order_id: int,
        *,
        event_type: str = "status",
        status: str | None = None,
        note: str | None = None,
        actor: str | None = None,
        meta: dict | None = None,
    ) -> OrderTimeline:
        entry = OrderTimeline(
            order_id=order_id,
            event_type=event_type,
            status=status,
            note=note,
            actor=actor,
            meta=meta,
        )
        await self.add(entry)
        return entry

    async def list_for_order(self, order_id: int) -> list[OrderTimeline]:
        result = await self.session.execute(
            select(OrderTimeline)
            .options(selectinload(OrderTimeline.order))
            .where(OrderTimeline.order_id == order_id)
            .order_by(OrderTimeline.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_orders_with_latest_status(
        self,
        status: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[Order]:
        latest = (
            select(
                OrderTimeline.order_id,
                func.max(OrderTimeline.id).label("latest_id"),
            )
            .where(OrderTimeline.event_type == "status")
            .group_by(OrderTimeline.order_id)
            .subquery()
        )

        query = (
            select(Order)
            .join(latest, latest.c.order_id == Order.id)
            .join(OrderTimeline, OrderTimeline.id == latest.c.latest_id)
            .options(
                joinedload(Order.user),
                joinedload(Order.product),
                selectinload(Order.answers),
            )
            .where(OrderTimeline.status == status)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self.session.execute(query)
        return list(result.scalars().unique().all())
