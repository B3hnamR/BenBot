from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import AdminActionLogRepository


class AdminActionLogService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AdminActionLogRepository(session)

    async def record(
        self,
        admin_id: int,
        action: str,
        *,
        order_id: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        await self._repo.add(admin_id=admin_id, action=action, order_id=order_id, meta=meta)

    async def list_recent(self, limit: int = 20):
        return await self._repo.list_recent(limit=limit)
