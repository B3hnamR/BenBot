from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.infrastructure.db.models import ProductBundleItem

from .base import BaseRepository


class ProductBundleRepository(BaseRepository):
    async def list_components(self, bundle_product_id: int) -> list[ProductBundleItem]:
        stmt = (
            select(ProductBundleItem)
            .options(joinedload(ProductBundleItem.component))
            .where(ProductBundleItem.bundle_product_id == bundle_product_id)
            .order_by(ProductBundleItem.position.asc(), ProductBundleItem.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def get_component(
        self,
        *,
        bundle_product_id: int,
        component_product_id: int,
    ) -> ProductBundleItem | None:
        stmt = (
            select(ProductBundleItem)
            .where(
                ProductBundleItem.bundle_product_id == bundle_product_id,
                ProductBundleItem.component_product_id == component_product_id,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def add_component(
        self,
        *,
        bundle_product_id: int,
        component_product_id: int,
        quantity: int,
        position: int,
    ) -> ProductBundleItem:
        item = ProductBundleItem(
            bundle_product_id=bundle_product_id,
            component_product_id=component_product_id,
            quantity=quantity,
        )
        item.position = position
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_component(
        self,
        item: ProductBundleItem,
        *,
        quantity: int | None = None,
        position: int | None = None,
    ) -> ProductBundleItem:
        if quantity is not None:
            item.quantity = quantity
        if position is not None:
            item.position = position
        await self.session.flush()
        return item

    async def remove_component(self, item: ProductBundleItem) -> None:
        await self.session.delete(item)
