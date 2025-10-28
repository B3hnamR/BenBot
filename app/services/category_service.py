from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Category, Product
from app.infrastructure.db.repositories import CategoryRepository


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._categories = CategoryRepository(session)

    async def list_active_categories(self) -> list[Category]:
        return list(await self._categories.list_active())

    async def list_all_categories(self) -> list[Category]:
        return list(await self._categories.list_all())

    async def get_category(self, category_id: int) -> Category | None:
        return await self._categories.get_by_id(category_id)

    async def list_category_products(self, category_id: int) -> list[Product]:
        category = await self._categories.get_by_id(category_id)
        if category is None:
            return []
        links = sorted(category.product_links or [], key=lambda link: link.position or 0)
        products: list[Product] = []
        for link in links:
            product = link.product
            if product is None:
                continue
            if product.is_active:
                products.append(product)
        return products
