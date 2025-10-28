from __future__ import annotations

from typing import Iterable, Sequence

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks.admin_products import ProductAdminCallback
from app.core.enums import ProductQuestionType
from app.infrastructure.db.models import (
    Category,
    Product,
    ProductBundleItem,
    ProductQuestion,
    ProductRelation,
)


def products_overview_keyboard(products: Sequence[Product]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for product in products:
        status = "[ON]" if product.is_active else "[OFF]"
        builder.button(
            text=f"{status} {product.name}",
            callback_data=ProductAdminCallback(action="view", product_id=product.id).pack(),
        )

    builder.button(
        text="Add product",
        callback_data=ProductAdminCallback(action="add").pack(),
    )
    builder.button(
        text="Manage categories",
        callback_data=ProductAdminCallback(action="categories").pack(),
    )
    builder.button(
        text="Back",
        callback_data=ProductAdminCallback(action="back_to_admin").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def product_detail_keyboard(product: Product) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    toggle_action = "Deactivate" if product.is_active else "Activate"
    builder.button(
        text=f"{toggle_action} product",
        callback_data=ProductAdminCallback(action="toggle", product_id=product.id).pack(),
    )
    builder.button(
        text="Edit details",
        callback_data=ProductAdminCallback(action="edit_menu", product_id=product.id).pack(),
    )
    builder.button(
        text="Manage form",
        callback_data=ProductAdminCallback(action="questions", product_id=product.id).pack(),
    )
    builder.button(
        text="Related products",
        callback_data=ProductAdminCallback(action="relations", product_id=product.id).pack(),
    )
    builder.button(
        text="Bundle components",
        callback_data=ProductAdminCallback(action="bundle", product_id=product.id).pack(),
    )
    builder.button(
        text="Delete",
        callback_data=ProductAdminCallback(action="delete", product_id=product.id).pack(),
    )
    builder.button(
        text="Back to list",
        callback_data=ProductAdminCallback(action="back_to_list").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def product_delete_confirm_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Confirm delete",
        callback_data=ProductAdminCallback(action="delete_confirm", product_id=product_id).pack(),
    )
    builder.button(
        text="Cancel",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def product_edit_fields_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fields = [
        ("Name", "name"),
        ("Summary", "summary"),
        ("Description", "description"),
        ("Price", "price"),
        ("Currency", "currency"),
        ("Inventory", "inventory"),
        ("Max per order", "max_per_order"),
        ("Inventory threshold", "inventory_threshold"),
        ("Position", "position"),
        ("Delivery message", "delivery_note"),
        ("Fulfillment plan (JSON)", "fulfillment_plan"),
    ]
    for label, field in fields:
        builder.button(
            text=label,
            callback_data=ProductAdminCallback(
                action="edit_field", product_id=product_id, value=field
            ).pack(),
        )
    builder.button(
        text="Back",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def categories_overview_keyboard(categories: Sequence[Category]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        status = "[ON]" if category.is_active else "[OFF]"
        builder.button(
            text=f"{status} {category.name}",
            callback_data=ProductAdminCallback(action="category_view", target_id=category.id).pack(),
        )
    builder.button(
        text="Add category",
        callback_data=ProductAdminCallback(action="category_add").pack(),
    )
    builder.button(
        text="Back to products",
        callback_data=ProductAdminCallback(action="back_to_list").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def category_detail_keyboard(category: Category) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for link in category.product_links or []:
        product = link.product
        name = product.name if product else f"Product #{link.product_id}"
        builder.button(
            text=f"Remove: {name[:32]}",
            callback_data=ProductAdminCallback(
                action="category_remove_product",
                target_id=category.id,
                value=str(link.product_id),
            ).pack(),
        )
    builder.button(
        text="Add product",
        callback_data=ProductAdminCallback(action="category_add_product", target_id=category.id).pack(),
    )
    builder.button(
        text="Toggle active",
        callback_data=ProductAdminCallback(action="category_toggle", target_id=category.id).pack(),
    )
    builder.button(
        text="Edit category",
        callback_data=ProductAdminCallback(action="category_edit_menu", target_id=category.id).pack(),
    )
    builder.button(
        text="Delete category",
        callback_data=ProductAdminCallback(action="category_delete", target_id=category.id).pack(),
    )
    builder.button(
        text="Back to categories",
        callback_data=ProductAdminCallback(action="categories").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def category_edit_fields_keyboard(category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    fields = [
        ("Name", "name"),
        ("Description", "description"),
        ("Position", "position"),
    ]
    for label, field in fields:
        builder.button(
            text=label,
            callback_data=ProductAdminCallback(
                action="category_edit_field",
                target_id=category_id,
                value=field,
            ).pack(),
        )
    builder.button(
        text="Back",
        callback_data=ProductAdminCallback(action="category_view", target_id=category_id).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def bundle_components_keyboard(
    product_id: int,
    components: Iterable[ProductBundleItem],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in components:
        component = item.component
        name = component.name if component else f"Product #{item.component_product_id}"
        qty = item.quantity
        builder.button(
            text=f"Remove: {name[:32]} (x{qty})",
            callback_data=ProductAdminCallback(
                action="bundle_remove",
                product_id=product_id,
                target_id=item.component_product_id,
            ).pack(),
        )
    builder.button(
        text="Add component",
        callback_data=ProductAdminCallback(action="bundle_add", product_id=product_id).pack(),
    )
    builder.button(
        text="Back",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def relations_keyboard(
    product_id: int,
    relations: Iterable[ProductRelation],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for relation in relations:
        related = relation.related_product
        name = related.name if related else f"Product #{relation.related_product_id}"
        label = f"{relation.relation_type.value}: {name[:28]} (w={relation.weight})"
        builder.button(
            text=label,
            callback_data=ProductAdminCallback(
                action="relation_remove",
                product_id=product_id,
                target_id=relation.related_product_id,
                value=relation.relation_type.value,
            ).pack(),
        )
    builder.button(
        text="Add relation",
        callback_data=ProductAdminCallback(action="relation_add", product_id=product_id).pack(),
    )
    builder.button(
        text="Back",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def category_creation_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Save category",
        callback_data=ProductAdminCallback(action="category_create_confirm").pack(),
    )
    builder.button(
        text="Cancel",
        callback_data=ProductAdminCallback(action="category_create_cancel").pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def category_delete_confirm_keyboard(category_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Confirm delete",
        callback_data=ProductAdminCallback(action="category_delete_confirm", target_id=category_id).pack(),
    )
    builder.button(
        text="Back",
        callback_data=ProductAdminCallback(action="category_view", target_id=category_id).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def product_questions_keyboard(
    product_id: int, questions: Iterable[ProductQuestion]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for question in questions:
        label = question.prompt or question.field_key
        builder.button(
            text=f"Delete: {label[:32]}",
            callback_data=ProductAdminCallback(
                action="question_delete", product_id=product_id, question_id=question.id
            ).pack(),
        )

    builder.button(
        text="Add question",
        callback_data=ProductAdminCallback(action="question_add", product_id=product_id).pack(),
    )
    builder.button(
        text="Back",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def question_delete_confirm_keyboard(
    product_id: int, question_id: int
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Confirm",
        callback_data=ProductAdminCallback(
            action="question_delete_confirm", product_id=product_id, question_id=question_id
        ).pack(),
    )
    builder.button(
        text="Cancel",
        callback_data=ProductAdminCallback(action="questions", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def question_type_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for question_type in ProductQuestionType:
        builder.button(
            text=question_type.value,
            callback_data=ProductAdminCallback(
                action="question_type_set", product_id=product_id, value=question_type.value
            ).pack(),
        )
    builder.adjust(2)
    return builder.as_markup()


def question_required_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Required",
        callback_data=ProductAdminCallback(
            action="question_required_set", product_id=product_id, value="true"
        ).pack(),
    )
    builder.button(
        text="Optional",
        callback_data=ProductAdminCallback(
            action="question_required_set", product_id=product_id, value="false"
        ).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def creation_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Save",
        callback_data=ProductAdminCallback(action="create_confirm").pack(),
    )
    builder.button(
        text="Cancel",
        callback_data=ProductAdminCallback(action="create_cancel").pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def question_creation_confirm_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Save question",
        callback_data=ProductAdminCallback(
            action="question_create_confirm", product_id=product_id
        ).pack(),
    )
    builder.button(
        text="Cancel",
        callback_data=ProductAdminCallback(
            action="question_create_cancel", product_id=product_id
        ).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()
