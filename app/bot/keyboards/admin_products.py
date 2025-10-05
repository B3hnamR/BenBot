from __future__ import annotations

from typing import Iterable, Sequence

from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks.admin_products import ProductAdminCallback
from app.core.enums import ProductQuestionType
from app.infrastructure.db.models import Product, ProductQuestion


def products_overview_keyboard(products: Sequence[Product]):
    builder = InlineKeyboardBuilder()

    for product in products:
        status_icon = "âœ…" if product.is_active else "ðŸš«"
        builder.button(
            text=f"{status_icon} {product.name}",
            callback_data=ProductAdminCallback(action="view", product_id=product.id).pack(),
        )

    builder.button(
        text="âž• Add product",
        callback_data=ProductAdminCallback(action="add").pack(),
    )
    builder.button(
        text="â¬…ï¸ Back",
        callback_data=ProductAdminCallback(action="back_to_admin").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def product_detail_keyboard(product: Product):
    builder = InlineKeyboardBuilder()

    toggle_action = "Deactivate" if product.is_active else "Activate"
    builder.button(
        text=f"{toggle_action} product",
        callback_data=ProductAdminCallback(action="toggle", product_id=product.id).pack(),
    )
    builder.button(
        text="âœï¸ Edit details",
        callback_data=ProductAdminCallback(action="edit_menu", product_id=product.id).pack(),
    )
    builder.button(
        text="ðŸ§¾ Manage form",
        callback_data=ProductAdminCallback(action="questions", product_id=product.id).pack(),
    )
    builder.button(
        text="ðŸ—‘ Delete",
        callback_data=ProductAdminCallback(action="delete", product_id=product.id).pack(),
    )
    builder.button(
        text="â¬…ï¸ Back to list",
        callback_data=ProductAdminCallback(action="back_to_list").pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def product_delete_confirm_keyboard(product_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="âœ… Confirm delete",
        callback_data=ProductAdminCallback(action="delete_confirm", product_id=product_id).pack(),
    )
    builder.button(
        text="â¬…ï¸ Cancel",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def product_edit_fields_keyboard(product_id: int):
    builder = InlineKeyboardBuilder()
    fields = [
        ("Name", "name"),
        ("Summary", "summary"),
        ("Description", "description"),
        ("Price", "price"),
        ("Currency", "currency"),
        ("Inventory", "inventory"),
        ("Position", "position"),
    ]
    for label, field in fields:
        builder.button(
            text=label,
            callback_data=ProductAdminCallback(
                action="edit_field", product_id=product_id, value=field
            ).pack(),
        )
    builder.button(
        text="â¬…ï¸ Back",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def product_questions_keyboard(product_id: int, questions: Iterable[ProductQuestion]):
    builder = InlineKeyboardBuilder()
    for question in questions:
        label = question.prompt or question.field_key
        builder.button(
            text=f"ðŸ—‘ {label[:32]}",
            callback_data=ProductAdminCallback(
                action="question_delete", product_id=product_id, question_id=question.id
            ).pack(),
        )

    builder.button(
        text="âž• Add question",
        callback_data=ProductAdminCallback(action="question_add", product_id=product_id).pack(),
    )
    builder.button(
        text="â¬…ï¸ Back",
        callback_data=ProductAdminCallback(action="view", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def question_delete_confirm_keyboard(product_id: int, question_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="âœ… Confirm",
        callback_data=ProductAdminCallback(
            action="question_delete_confirm", product_id=product_id, question_id=question_id
        ).pack(),
    )
    builder.button(
        text="â¬…ï¸ Cancel",
        callback_data=ProductAdminCallback(action="questions", product_id=product_id).pack(),
    )
    builder.adjust(1)
    return builder.as_markup()


def question_type_keyboard(product_id: int):
    builder = InlineKeyboardBuilder()
    for question_type in ProductQuestionType:
        builder.button(
            text=question_type.value.title(),
            callback_data=ProductAdminCallback(
                action="question_type_set", product_id=product_id, value=question_type.value
            ).pack(),
        )
    builder.adjust(2)
    return builder.as_markup()


def question_required_keyboard(product_id: int):
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


def creation_confirm_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(
        text="âœ… Save",
        callback_data=ProductAdminCallback(action="create_confirm").pack(),
    )
    builder.button(
        text="â¬…ï¸ Cancel",
        callback_data=ProductAdminCallback(action="create_cancel").pack(),
    )
    builder.adjust(2)
    return builder.as_markup()


def question_creation_confirm_keyboard(product_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="âœ… Save question",
        callback_data=ProductAdminCallback(
            action="question_create_confirm", product_id=product_id
        ).pack(),
    )
    builder.button(
        text="â¬…ï¸ Cancel",
        callback_data=ProductAdminCallback(
            action="question_create_cancel", product_id=product_id
        ).pack(),
    )
    builder.adjust(2)
    return builder.as_markup()