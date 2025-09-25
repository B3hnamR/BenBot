from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.infrastructure.db.models import Product

from .base import BaseRepository


class ProductRepository(BaseRepository):
    async def list_active(self) -> list[Product]:
        result = await self.session.execute(
            select(Product)
            .options(joinedload(Product.questions))
            .where(Product.is_active.is_(True))
            .order_by(Product.position.asc(), Product.created_at.desc())
        )
        return list(result.scalars().unique())

    async def get_by_slug(self, slug: str) -> Product | None:
        result = await self.session.execute(
            select(Product)
            .options(joinedload(Product.questions))
            .where(Product.slug == slug)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, product_id: int) -> Product | None:
        result = await self.session.execute(
            select(Product)
            .options(joinedload(Product.questions))
            .where(Product.id == product_id)
        )
        return result.scalar_one_or_none()
