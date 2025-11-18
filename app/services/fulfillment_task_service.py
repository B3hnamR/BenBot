from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Order, OrderFulfillmentTask
from app.infrastructure.db.repositories import FulfillmentTaskRepository


class FulfillmentTaskService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = FulfillmentTaskRepository(session)

    async def record_failure(self, order: Order, *, source: str, error: str) -> OrderFulfillmentTask:
        task = await self._repo.get_by_order_id(order.id)
        now = datetime.now(tz=timezone.utc)
        if task is None:
            task = OrderFulfillmentTask(order_id=order.id)
            self._session.add(task)
        task.status = "failed"
        task.source = source
        task.last_error = (error or "")[:2000]
        task.attempts = int(task.attempts or 0) + 1
        task.last_attempted_at = now
        task.resolved_at = None
        await self._session.flush()
        return task

    async def clear_for_order(self, order: Order) -> None:
        task = await self._repo.get_by_order_id(order.id)
        if task is None:
            return
        task.status = "resolved"
        task.resolved_at = datetime.now(tz=timezone.utc)
        await self._session.flush()

    async def list_open(self, limit: int = 20) -> list[OrderFulfillmentTask]:
        return await self._repo.list_open(limit=limit)

    async def get_task(self, task_id: int) -> OrderFulfillmentTask | None:
        return await self._repo.get_by_id(task_id)

    async def dismiss(self, task: OrderFulfillmentTask) -> None:
        task.status = "dismissed"
        task.resolved_at = datetime.now(tz=timezone.utc)
        await self._session.flush()
