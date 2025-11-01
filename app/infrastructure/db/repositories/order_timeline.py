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
