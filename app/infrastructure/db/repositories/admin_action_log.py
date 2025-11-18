from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.infrastructure.db.models import AdminActionLog, Order

from .base import BaseRepository


class AdminActionLogRepository(BaseRepository):
    async def add(self, admin_id: int, action: str, order_id: int | None, meta: dict | None) -> AdminActionLog:
        log = AdminActionLog(
            admin_id=admin_id,
            action=action,
            order_id=order_id,
            meta=meta,
        )
        await super().add(log)
        return log

    async def list_recent(self, limit: int = 20) -> list[AdminActionLog]:
        result = await self.session.execute(
            select(AdminActionLog)
            .options(joinedload(AdminActionLog.order).joinedload(Order.product))
            .order_by(AdminActionLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())
