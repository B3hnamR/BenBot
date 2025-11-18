from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.db.models import InstantInventoryItem

from .base import BaseRepository


class InstantInventoryRepository(BaseRepository):
    async def add_item(
        self,
        product_id: int,
        *,
        label: str,
        payload: str | None = None,
        meta: dict | None = None,
    ) -> InstantInventoryItem:
        item = InstantInventoryItem(
            product_id=product_id,
            label=label,
            payload=payload,
            meta=meta,
        )
        await self.add(item)
        return item

    async def list_available(self, product_id: int, limit: int = 10) -> list[InstantInventoryItem]:
        result = await self.session.execute(
            select(InstantInventoryItem)
            .where(
                InstantInventoryItem.product_id == product_id,
                InstantInventoryItem.is_consumed.is_(False),
            )
            .order_by(InstantInventoryItem.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def consume_first(self, product_id: int, *, order_id: int) -> InstantInventoryItem | None:
        result = await self.session.execute(
            select(InstantInventoryItem)
            .where(
                InstantInventoryItem.product_id == product_id,
                InstantInventoryItem.is_consumed.is_(False),
            )
            .order_by(InstantInventoryItem.id.asc())
            .limit(1)
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None
        item.is_consumed = True
        item.order_id = order_id
        from datetime import datetime, timezone

        item.consumed_at = datetime.now(tz=timezone.utc)
        await self.session.flush()
        return item
