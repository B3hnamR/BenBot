from __future__ import annotations

from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import InstantInventoryItem, Order, Product
from app.infrastructure.db.repositories import InstantInventoryRepository


class InstantInventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = InstantInventoryRepository(session)

    async def add_item(
        self,
        product: Product,
        *,
        label: str,
        payload: str | None = None,
        metadata: dict | None = None,
    ) -> InstantInventoryItem:
        return await self._repo.add_item(
            product_id=product.id,
            label=label,
            payload=payload,
            metadata=metadata,
        )

    async def list_available(self, product: Product, limit: int = 10) -> list[InstantInventoryItem]:
        return await self._repo.list_available(product.id, limit=limit)

    async def consume_for_order(self, order: Order) -> InstantInventoryItem | None:
        product = order.product
        if product is None or not getattr(product, "instant_delivery_enabled", False):
            return None
        if order.id is None:
            await self._session.flush()
        return await self._repo.consume_first(product.id, order_id=order.id)
