from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.repositories import ProductRepository


class ProductService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = ProductRepository(session)

    async def list_active_products(self):
        return await self._repo.list_active()

    async def get_product(self, product_id: int):
        return await self._repo.get_by_id(product_id)

    async def get_product_by_slug(self, slug: str):
        return await self._repo.get_by_slug(slug)
