from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ProductRelationType
from app.infrastructure.db.models import Product
from app.infrastructure.db.repositories import ProductRelationRepository, ProductRepository


class RecommendationService:
    """
    Retrieves suggested products for cross-sell/upsell flows.

    The service consults explicit relations first and can fall back to catalogue heuristics.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._relations = ProductRelationRepository(session)
        self._products = ProductRepository(session)

    async def get_related_products(
        self,
        product_id: int,
        *,
        relation_types: set[ProductRelationType] | None = None,
        limit: int = 4,
    ) -> list[Product]:
        relations = await self._relations.list_for_product(product_id, relation_types=relation_types or None)
        products: list[Product] = []
        seen: set[int] = set()
        for relation in relations:
            related = relation.related_product
            if related is None or not related.is_active:
                continue
            if related.id in seen:
                continue
            products.append(related)
            seen.add(related.id)
            if len(products) >= limit:
                break
        if len(products) >= limit:
            return products[:limit]

        # Optional TODO: implement heuristics (e.g., top sellers). For now we return what we have.
        source_product = await self._products.get_by_id(product_id)
        if source_product is not None:
            for link in source_product.category_links or []:
                category = link.category
                if category is None:
                    continue
                for peer_link in category.product_links or []:
                    candidate = peer_link.product
                    if candidate is None or not candidate.is_active:
                        continue
                    if candidate.id == product_id or candidate.id in seen:
                        continue
                    products.append(candidate)
                    seen.add(candidate.id)
                    if len(products) >= limit:
                        return products[:limit]

        return products[:limit]
