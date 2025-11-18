from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.infrastructure.db.models import Order, OrderFulfillmentTask

from .base import BaseRepository


class FulfillmentTaskRepository(BaseRepository):
    async def get_by_order_id(self, order_id: int) -> OrderFulfillmentTask | None:
        result = await self.session.execute(
            select(OrderFulfillmentTask).where(OrderFulfillmentTask.order_id == order_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, task_id: int) -> OrderFulfillmentTask | None:
        result = await self.session.execute(
            select(OrderFulfillmentTask)
            .options(joinedload(OrderFulfillmentTask.order).joinedload(Order.product))
            .where(OrderFulfillmentTask.id == task_id)
        )
        return result.scalar_one_or_none()

    async def list_open(self, limit: int = 20) -> list[OrderFulfillmentTask]:
        result = await self.session.execute(
            select(OrderFulfillmentTask)
            .options(joinedload(OrderFulfillmentTask.order).joinedload(Order.product))
            .where(OrderFulfillmentTask.status != "resolved")
            .order_by(OrderFulfillmentTask.updated_at.desc().nullslast())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def delete(self, task: OrderFulfillmentTask) -> None:
        await self.session.delete(task)
