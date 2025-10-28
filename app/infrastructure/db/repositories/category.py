from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from app.infrastructure.db.models import Category, ProductCategory

from .base import BaseRepository


class CategoryRepository(BaseRepository):
    async def list_all(self) -> Sequence[Category]:
        stmt = (
            select(Category)
            .options(
                selectinload(Category.product_links).options(
                    joinedload(ProductCategory.product)
                )
            )
            .order_by(Category.position.asc(), Category.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def list_active(self) -> list[Category]:
        stmt = (
            select(Category)
            .options(
                selectinload(Category.product_links).options(
                    joinedload(ProductCategory.product)
                )
            )
            .where(Category.is_active.is_(True))
            .order_by(Category.position.asc(), Category.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def get_by_id(self, category_id: int) -> Category | None:
        stmt = (
            select(Category)
            .options(
                selectinload(Category.product_links).options(
                    joinedload(ProductCategory.product)
                )
            )
            .where(Category.id == category_id)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Category | None:
        stmt = (
            select(Category)
            .options(selectinload(Category.product_links))
            .where(Category.slug == slug)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(func.count()).select_from(Category).where(Category.slug == slug)
        result = await self.session.execute(stmt)
        return bool(result.scalar())

    async def create_category(self, category: Category) -> Category:
        self.session.add(category)
        await self.session.flush()
        return category

    async def delete(self, category: Category) -> None:
        await self.session.delete(category)

    async def get_next_position(self) -> int:
        stmt = select(func.max(Category.position))
        result = await self.session.execute(stmt)
        max_position = result.scalar()
        return (max_position or 0) + 1

    async def get_link(
        self,
        *,
        category_id: int,
        product_id: int,
    ) -> ProductCategory | None:
        stmt = select(ProductCategory).where(
            ProductCategory.category_id == category_id,
            ProductCategory.product_id == product_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def attach_product(
        self,
        category: Category,
        product_id: int,
        *,
        position: int | None = None,
    ) -> ProductCategory:
        existing = await self.get_link(category_id=category.id, product_id=product_id)
        if existing:
            if position is not None:
                existing.position = position
            return existing

        if position is None:
            position = await self._next_product_position(category.id)

        link = ProductCategory(
            category_id=category.id,
            product_id=product_id,
            position=position,
        )
        self.session.add(link)
        await self.session.flush()
        return link

    async def detach_product(self, link: ProductCategory) -> None:
        await self.session.delete(link)

    async def reorder_links(self, category: Category) -> None:
        links = sorted(category.product_links or [], key=lambda item: item.position or 0)
        for index, link in enumerate(links, start=1):
            link.position = index
        await self.session.flush()

    async def _next_product_position(self, category_id: int) -> int:
        stmt = select(func.max(ProductCategory.position)).where(
            ProductCategory.category_id == category_id
        )
        result = await self.session.execute(stmt)
        max_position = result.scalar()
        return (max_position or 0) + 1
