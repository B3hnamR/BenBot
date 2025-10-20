from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.enums import ProductRelationType
from app.infrastructure.db.models import ProductRelation

from .base import BaseRepository


class ProductRelationRepository(BaseRepository):
    async def list_for_product(
        self,
        product_id: int,
        *,
        relation_types: set[ProductRelationType] | None = None,
    ) -> list[ProductRelation]:
        stmt = (
            select(ProductRelation)
            .options(selectinload(ProductRelation.related_product))
            .where(ProductRelation.product_id == product_id)
            .order_by(ProductRelation.weight.desc(), ProductRelation.created_at.desc())
        )
        if relation_types:
            stmt = stmt.where(ProductRelation.relation_type.in_(list(relation_types)))
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def add_relation(
        self,
        *,
        product_id: int,
        related_product_id: int,
        relation_type: ProductRelationType,
        weight: int = 0,
    ) -> ProductRelation:
        relation = ProductRelation(
            product_id=product_id,
            related_product_id=related_product_id,
            relation_type=relation_type,
            weight=weight,
        )
        await self.add(relation)
        return relation

    async def delete_relation(self, relation: ProductRelation) -> None:
        await self.session.delete(relation)

    async def get_relation(
        self,
        *,
        product_id: int,
        related_product_id: int,
        relation_type: ProductRelationType,
    ) -> ProductRelation | None:
        result = await self.session.execute(
            select(ProductRelation)
            .where(
                ProductRelation.product_id == product_id,
                ProductRelation.related_product_id == related_product_id,
                ProductRelation.relation_type == relation_type,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
