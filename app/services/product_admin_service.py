from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ProductQuestionType, ProductRelationType
from app.infrastructure.db.models import (
    Category,
    Product,
    ProductBundleItem,
    ProductCategory,
    ProductQuestion,
    ProductRelation,
)
from app.infrastructure.db.repositories import (
    CategoryRepository,
    ProductBundleRepository,
    ProductQuestionRepository,
    ProductRelationRepository,
    ProductRepository,
)


class ProductAdminError(RuntimeError):
    """Base error for product administration."""


class ProductNotFoundError(ProductAdminError):
    """Raised when a product is missing."""


class ProductQuestionNotFoundError(ProductAdminError):
    """Raised when a product question is missing."""


class ProductValidationError(ProductAdminError):
    """Raised when provided data is invalid."""


class CategoryNotFoundError(ProductAdminError):
    """Raised when a category is missing."""


class CategoryValidationError(ProductAdminError):
    """Raised when category data is invalid."""


class BundleConfigurationError(ProductAdminError):
    """Raised when bundle configuration is invalid."""


@dataclass(slots=True)
class ProductInput:
    name: str
    summary: str | None
    description: str | None
    price: Decimal
    currency: str
    inventory: int | None
    position: int | None
    max_per_order: int | None = None
    inventory_threshold: int | None = None


@dataclass(slots=True)
class CategoryInput:
    name: str
    description: str | None
    is_active: bool = True
    position: int | None = None
    meta: dict | None = None


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
        self._products = ProductRepository(session)
        self._questions = ProductQuestionRepository(session)
        self._categories = CategoryRepository(session)
        self._bundles = ProductBundleRepository(session)
        self._relations = ProductRelationRepository(session)

    async def list_products(self) -> list[Product]:
        return list(await self._products.list_all())

    async def get_product(self, product_id: int) -> Product:
        product = await self._products.get_by_id(product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {product_id} not found")
        return product

    async def create_product(self, data: ProductInput) -> Product:
        slug = await self._generate_unique_slug(data.name)
        position = data.position
        if position is None:
            position = await self._products.get_next_position()

        product = Product(
            name=data.name,
            slug=slug,
            summary=data.summary,
            description=data.description,
            price=data.price,
            currency=data.currency,
            inventory=data.inventory,
             max_per_order=data.max_per_order,
             inventory_threshold=data.inventory_threshold,
            is_active=False,
            position=position,
            extra_attrs=None,
        )
        await self._products.add_product(product)
        return product

    async def update_product(self, product_id: int, **fields: object) -> Product:
        product = await self.get_product(product_id)

        if "name" in fields and fields["name"]:
            new_name = str(fields["name"]).strip()
            if not new_name:
                raise ProductValidationError("Name cannot be empty.")
            if new_name != product.name:
                product.name = new_name
                product.slug = await self._generate_unique_slug(
                    new_name,
                    current_slug=product.slug,
                )

        if "inventory" in fields:
            inventory = fields["inventory"]
            if inventory in (None, ""):
                fields["inventory"] = None
            else:
                try:
                    inventory_value = int(inventory) if not isinstance(inventory, int) else inventory
                except (TypeError, ValueError) as exc:
                    raise ProductValidationError("Inventory must be an integer or empty for unlimited.") from exc
                if inventory_value < 0:
                    raise ProductValidationError("Inventory cannot be negative.")
                fields["inventory"] = inventory_value

        if "max_per_order" in fields:
            max_per_order = fields["max_per_order"]
            if max_per_order in (None, ""):
                fields["max_per_order"] = None
            else:
                try:
                    max_value = int(max_per_order) if not isinstance(max_per_order, int) else max_per_order
                except (TypeError, ValueError) as exc:
                    raise ProductValidationError("Max per order must be a positive integer.") from exc
                if max_value <= 0:
                    raise ProductValidationError("Max per order must be greater than zero.")
                fields["max_per_order"] = max_value

        if "inventory_threshold" in fields:
            threshold = fields["inventory_threshold"]
            if threshold in (None, ""):
                fields["inventory_threshold"] = None
            else:
                try:
                    threshold_value = int(threshold) if not isinstance(threshold, int) else threshold
                except (TypeError, ValueError) as exc:
                    raise ProductValidationError("Inventory threshold must be a non-negative integer.") from exc
                if threshold_value < 0:
                    raise ProductValidationError("Inventory threshold cannot be negative.")
                fields["inventory_threshold"] = threshold_value

        extras = dict(product.extra_attrs or {})

        if "delivery_note" in fields:
            note_value = fields["delivery_note"]
            if note_value in (None, ""):
                extras.pop("delivery_note", None)
            else:
                extras["delivery_note"] = str(note_value)

        if "fulfillment_plan" in fields:
            plan_value = fields["fulfillment_plan"]
            if plan_value in (None, ""):
                extras.pop("fulfillment_plan", None)
            else:
                extras["fulfillment_plan"] = plan_value

        if extras:
            product.extra_attrs = extras
        else:
            product.extra_attrs = None

        for attr in (
            "summary",
            "description",
            "price",
            "currency",
            "inventory",
            "position",
            "max_per_order",
            "inventory_threshold",
            "is_active",
        ):
            if attr in fields:
                setattr(product, attr, fields[attr])

        await self._session.flush()
        return product

    async def toggle_product_active(self, product_id: int) -> Product:
        product = await self.get_product(product_id)
        product.is_active = not product.is_active
        await self._session.flush()
        return product

    async def delete_product(self, product_id: int) -> None:
        product = await self.get_product(product_id)
        await self._products.delete(product)

    async def list_categories(self) -> list[Category]:
        return list(await self._categories.list_all())

    async def get_category(self, category_id: int) -> Category:
        category = await self._categories.get_by_id(category_id)
        if category is None:
            raise CategoryNotFoundError(f"Category {category_id} not found")
        return category

    async def create_category(self, data: CategoryInput) -> Category:
        slug = await self._generate_unique_category_slug(data.name)
        position = data.position
        if position is None:
            position = await self._categories.get_next_position()

        category = Category(
            name=data.name,
            slug=slug,
            description=data.description,
            position=position,
            is_active=data.is_active,
            meta=data.meta,
        )
        await self._categories.create_category(category)
        return category

    async def update_category(self, category_id: int, **fields: object) -> Category:
        category = await self.get_category(category_id)

        if "name" in fields and fields["name"]:
            new_name = str(fields["name"]).strip()
            if not new_name:
                raise CategoryValidationError("Name cannot be empty.")
            if new_name != category.name:
                category.name = new_name
                category.slug = await self._generate_unique_category_slug(
                    new_name,
                    current_slug=category.slug,
                )

        if "description" in fields:
            category.description = fields["description"]

        if "position" in fields and fields["position"] is not None:
            try:
                category.position = int(fields["position"])
            except (TypeError, ValueError) as exc:
                raise CategoryValidationError("Position must be an integer.") from exc

        if "is_active" in fields and fields["is_active"] is not None:
            category.is_active = bool(fields["is_active"])

        if "meta" in fields:
            category.meta = fields["meta"]

        await self._session.flush()
        return category

    async def toggle_category_active(self, category_id: int) -> Category:
        category = await self.get_category(category_id)
        category.is_active = not category.is_active
        await self._session.flush()
        return category

    async def delete_category(self, category_id: int) -> None:
        category = await self.get_category(category_id)
        await self._categories.delete(category)

    async def attach_product_to_category(
        self,
        *,
        category_id: int,
        product_id: int,
        position: int | None = None,
    ) -> ProductCategory:
        category = await self.get_category(category_id)
        await self.get_product(product_id)
        link = await self._categories.attach_product(
            category,
            product_id=product_id,
            position=position,
        )
        await self._session.flush()
        return link

    async def detach_product_from_category(self, *, category_id: int, product_id: int) -> None:
        link = await self._categories.get_link(category_id=category_id, product_id=product_id)
        if link is None:
            return
        await self._categories.detach_product(link)
        await self._session.flush()

    async def reorder_category_products(self, category_id: int, product_ids: list[int]) -> None:
        category = await self.get_category(category_id)
        links = {link.product_id: link for link in category.product_links or []}
        current = set(links)
        order_map = {product_id: index for index, product_id in enumerate(product_ids, start=1) if product_id in current}

        next_position = len(order_map) + 1
        for product_id, link in links.items():
            if product_id in order_map:
                link.position = order_map[product_id]
            else:
                link.position = next_position
                next_position += 1
        await self._session.flush()

    async def list_bundle_items(self, bundle_product_id: int) -> list[ProductBundleItem]:
        await self.get_product(bundle_product_id)
        return await self._bundles.list_components(bundle_product_id)

    async def add_bundle_item(
        self,
        *,
        bundle_product_id: int,
        component_product_id: int,
        quantity: int,
    ) -> ProductBundleItem:
        if bundle_product_id == component_product_id:
            raise BundleConfigurationError("A bundle cannot contain itself as a component.")

        bundle = await self.get_product(bundle_product_id)
        await self.get_product(component_product_id)

        if quantity <= 0:
            raise BundleConfigurationError("Quantity must be greater than zero.")

        existing = await self._bundles.get_component(
            bundle_product_id=bundle.id,
            component_product_id=component_product_id,
        )
        if existing:
            existing.quantity = quantity
            await self._session.flush()
            return existing

        components = await self._bundles.list_components(bundle.id)
        position = len(components) + 1
        item = await self._bundles.add_component(
            bundle_product_id=bundle.id,
            component_product_id=component_product_id,
            quantity=quantity,
            position=position,
        )
        await self._session.flush()
        return item

    async def update_bundle_item(
        self,
        *,
        bundle_product_id: int,
        component_product_id: int,
        quantity: int | None = None,
        position: int | None = None,
    ) -> ProductBundleItem:
        item = await self._bundles.get_component(
            bundle_product_id=bundle_product_id,
            component_product_id=component_product_id,
        )
        if item is None:
            raise BundleConfigurationError("Bundle component not found.")

        if quantity is not None:
            if quantity <= 0:
                raise BundleConfigurationError("Quantity must be greater than zero.")

        if position is not None and position <= 0:
            raise BundleConfigurationError("Position must be positive.")

        await self._bundles.update_component(item, quantity=quantity, position=position)
        await self._session.flush()
        return item

    async def remove_bundle_item(
        self,
        *,
        bundle_product_id: int,
        component_product_id: int,
    ) -> None:
        item = await self._bundles.get_component(
            bundle_product_id=bundle_product_id,
            component_product_id=component_product_id,
        )
        if item is None:
            return
        await self._bundles.remove_component(item)
        await self._session.flush()

    async def reorder_bundle_items(self, bundle_product_id: int, component_ids: list[int]) -> None:
        items = await self._bundles.list_components(bundle_product_id)
        by_component = {item.component_product_id: item for item in items}
        order_map = {component_id: index for index, component_id in enumerate(component_ids, start=1) if component_id in by_component}
        next_position = len(order_map) + 1
        for component_id, item in by_component.items():
            if component_id in order_map:
                item.position = order_map[component_id]
            else:
                item.position = next_position
                next_position += 1
        await self._session.flush()

    async def list_relations(
        self,
        product_id: int,
        relation_types: set[ProductRelationType] | None = None,
    ) -> list[ProductRelation]:
        await self.get_product(product_id)
        return await self._relations.list_for_product(product_id, relation_types=relation_types)

    async def add_relation(
        self,
        *,
        product_id: int,
        related_product_id: int,
        relation_type: ProductRelationType,
        weight: int = 0,
    ) -> ProductRelation:
        if product_id == related_product_id:
            raise ProductValidationError("Cannot relate a product to itself.")

        await self.get_product(product_id)
        await self.get_product(related_product_id)

        existing = await self._relations.get_relation(
            product_id=product_id,
            related_product_id=related_product_id,
            relation_type=relation_type,
        )
        if existing:
            existing.weight = weight
            await self._session.flush()
            return existing

        relation = await self._relations.add_relation(
            product_id=product_id,
            related_product_id=related_product_id,
            relation_type=relation_type,
            weight=weight,
        )
        await self._session.flush()
        return relation

    async def remove_relation(
        self,
        *,
        product_id: int,
        related_product_id: int,
        relation_type: ProductRelationType,
    ) -> None:
        relation = await self._relations.get_relation(
            product_id=product_id,
            related_product_id=related_product_id,
            relation_type=relation_type,
        )
        if relation is None:
            return
        await self._relations.delete_relation(relation)
        await self._session.flush()

    async def list_questions(self, product_id: int) -> list[ProductQuestion]:
        return await self._questions.list_for_product(product_id)

    async def add_question(self, data: QuestionInput) -> ProductQuestion:
        await self.get_product(data.product_id)

        existing = {
            question.field_key
            for question in await self._questions.list_for_product(data.product_id)
        }
        if data.field_key in existing:
            raise ProductValidationError("Field key already exists for this product.")

        position = await self._questions.get_next_position(data.product_id)
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
        await self._questions.add_question(question)
        return question

    async def delete_question(self, question_id: int) -> None:
        question = await self._questions.get_by_id(question_id)
        if question is None:
            raise ProductQuestionNotFoundError(f"Question {question_id} not found")
        product_id = question.product_id
        await self._questions.delete(question)
        await self._questions.reorder_positions(product_id)

    async def _generate_unique_slug(
        self,
        name: str,
        *,
        current_slug: str | None = None,
    ) -> str:
        base_slug = self._slugify(name)
        if not await self._products.slug_exists(base_slug) or base_slug == current_slug:
            return base_slug

        suffix = 2
        while True:
            candidate = f"{base_slug}-{suffix}"
            if not await self._products.slug_exists(candidate) or candidate == current_slug:
                return candidate
            suffix += 1

    async def _generate_unique_category_slug(
        self,
        name: str,
        *,
        current_slug: str | None = None,
    ) -> str:
        base_slug = self._slugify(name)
        if not await self._categories.slug_exists(base_slug) or base_slug == current_slug:
            return base_slug

        suffix = 2
        while True:
            candidate = f"{base_slug}-{suffix}"
            if not await self._categories.slug_exists(candidate) or candidate == current_slug:
                return candidate
            suffix += 1

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        normalized = normalized.lower()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
        return slug or "product"
