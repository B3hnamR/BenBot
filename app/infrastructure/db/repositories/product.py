from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from app.infrastructure.db.models import Product, ProductBundleItem, ProductCategory, ProductRelation

from .base import BaseRepository


class ProductRepository(BaseRepository):
    async def list_active(self) -> list[Product]:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.questions),
                selectinload(Product.categories),
                selectinload(Product.category_links).joinedload(ProductCategory.category),
                selectinload(Product.bundle_components).joinedload(ProductBundleItem.component),
                selectinload(Product.related_products).joinedload(ProductRelation.related_product),
            )
            .where(Product.is_active.is_(True))
            .order_by(Product.position.asc(), Product.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique())

    async def list_all(self) -> Sequence[Product]:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.questions),
                selectinload(Product.categories),
                selectinload(Product.category_links).joinedload(ProductCategory.category),
                selectinload(Product.bundle_components).joinedload(ProductBundleItem.component),
                selectinload(Product.related_products).joinedload(ProductRelation.related_product),
            )
            .order_by(Product.position.asc(), Product.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().unique().all()

    async def get_by_slug(self, slug: str) -> Product | None:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.questions),
                selectinload(Product.categories),
                selectinload(Product.category_links).joinedload(ProductCategory.category),
                selectinload(Product.bundle_components).joinedload(ProductBundleItem.component),
                selectinload(Product.related_products).joinedload(ProductRelation.related_product),
            )
            .where(Product.slug == slug)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def get_by_id(self, product_id: int) -> Product | None:
        stmt = (
            select(Product)
            .options(
                selectinload(Product.questions),
                selectinload(Product.categories),
                selectinload(Product.category_links).joinedload(ProductCategory.category),
                selectinload(Product.bundle_components).joinedload(ProductBundleItem.component),
                selectinload(Product.related_products).joinedload(ProductRelation.related_product),
            )
            .where(Product.id == product_id)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        result = await self.session.execute(
            select(func.count()).select_from(Product).where(Product.slug == slug)
        )
        return bool(result.scalar())

    async def add_product(self, product: Product) -> Product:
        self.session.add(product)
        await self.session.flush()
        return product

    async def delete(self, product: Product) -> None:
        await self.session.delete(product)

    async def get_next_position(self) -> int:
        result = await self.session.execute(select(func.max(Product.position)))
        max_position = result.scalar()
        return (max_position or 0) + 1
