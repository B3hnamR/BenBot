from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.infrastructure.db.models import OrderFeedback, Order, UserProfile

from .base import BaseRepository


class OrderFeedbackRepository(BaseRepository):
    async def get_by_order_id(self, order_id: int) -> OrderFeedback | None:
        result = await self.session.execute(
            select(OrderFeedback).where(OrderFeedback.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 20) -> list[OrderFeedback]:
        result = await self.session.execute(
            select(OrderFeedback)
            .options(
                joinedload(OrderFeedback.order).joinedload(Order.product),
                joinedload(OrderFeedback.user),
            )
            .order_by(OrderFeedback.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())
