from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ProductQuestionType
from app.infrastructure.db.models import Product, ProductQuestion
from app.infrastructure.db.repositories import (
    ProductQuestionRepository,
    ProductRepository,
)


class ProductAdminError(RuntimeError):
    """Base error for product administration operations."""


class ProductNotFoundError(ProductAdminError):
    pass


class ProductQuestionNotFoundError(ProductAdminError):
    pass


class ProductValidationError(ProductAdminError):
    pass


@dataclass(slots=True)
class ProductInput:
    name: str
    summary: str | None
    description: str | None
    price: Decimal
    currency: str
    inventory: int | None
    position: int | None


@dataclass(slots=True)
class QuestionInput:
    product_id: int
    field_key: str
    prompt: str
    help_text: str | None
    question_type: ProductQuestionType
    is_required: bool
    config: dict | None


class ProductAdminService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._product_repo = ProductRepository(session)
        self._question_repo = ProductQuestionRepository(session)

    async def list_products(self) -> Sequence[Product]:
        return await self._product_repo.list_all()

    async def get_product(self, product_id: int) -> Product:
        product = await self._product_repo.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {product_id} not found")
        return product

    async def create_product(self, data: ProductInput) -> Product:
        slug = await self._generate_unique_slug(data.name)
        position = data.position
        if position is None:
            position = await self._product_repo.get_next_position()

        product = Product(
            name=data.name,
            slug=slug,
            summary=data.summary,
            description=data.description,
            price=data.price,
            currency=data.currency,
            inventory=data.inventory,
            is_active=False,
            position=position,
            extra_attrs=None,
        )
        await self._product_repo.add_product(product)
        return product

    async def update_product(self, product_id: int, **fields: object) -> Product:
        product = await self.get_product(product_id)

        if "name" in fields and fields["name"] is not None:
            new_name = str(fields["name"])
            if new_name and new_name != product.name:
                product.name = new_name
                product.slug = await self._generate_unique_slug(new_name, current_slug=product.slug)

        for attr in ("summary", "description", "price", "currency", "inventory", "position", "extra_attrs", "is_active"):
            if attr in fields and fields[attr] is not None:
                setattr(product, attr, fields[attr])

        # Fields explicitly set to None should also be cleared
        for attr, value in fields.items():
            if value is None and attr in {"summary", "description", "inventory", "extra_attrs"}:
                setattr(product, attr, None)

        await self._session.flush()
        return product

    async def toggle_product_active(self, product_id: int) -> Product:
        product = await self.get_product(product_id)
        product.is_active = not product.is_active
        await self._session.flush()
        return product

    async def delete_product(self, product_id: int) -> None:
        product = await self.get_product(product_id)
        await self._product_repo.delete(product)

    async def list_questions(self, product_id: int) -> Sequence[ProductQuestion]:
        return await self._question_repo.list_for_product(product_id)

    async def add_question(self, data: QuestionInput) -> ProductQuestion:
        # ensure product exists
        await self.get_product(data.product_id)

        existing_fields = {q.field_key for q in await self._question_repo.list_for_product(data.product_id)}
        if data.field_key in existing_fields:
            raise ProductValidationError("Field key already exists for this product")

        position = await self._question_repo.get_next_position(data.product_id)
        question = ProductQuestion(
            product_id=data.product_id,
            field_key=data.field_key,
            prompt=data.prompt,
            help_text=data.help_text,
            question_type=data.question_type,
            is_required=data.is_required,
            position=position,
            config=data.config,
        )
        await self._question_repo.add_question(question)
        return question

    async def delete_question(self, question_id: int) -> None:
        question = await self._question_repo.get_by_id(question_id)
        if question is None:
            raise ProductQuestionNotFoundError(f"Question {question_id} not found")
        product_id = question.product_id
        await self._question_repo.delete(question)
        await self._question_repo.reorder_positions(product_id)

    async def _generate_unique_slug(self, name: str, *, current_slug: str | None = None) -> str:
        base_slug = self._slugify(name)
        if not await self._product_repo.slug_exists(base_slug) or base_slug == current_slug:
            return base_slug

        suffix = 2
        while True:
            candidate = f"{base_slug}-{suffix}"
            if not await self._product_repo.slug_exists(candidate) or candidate == current_slug:
                return candidate
            suffix += 1

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        normalized = normalized.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        return slug or "product"