
from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation
from typing import Iterable, Sequence

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks.admin_products import ProductAdminCallback
from app.bot.keyboards.admin import AdminMenuCallback, admin_menu_keyboard
from app.bot.keyboards.admin_products import (
    creation_confirm_keyboard,
    product_delete_confirm_keyboard,
    product_detail_keyboard,
    product_edit_fields_keyboard,
    product_questions_keyboard,
    products_overview_keyboard,
    question_creation_confirm_keyboard,
    question_delete_confirm_keyboard,
    question_required_keyboard,
    question_type_keyboard,
)
from app.bot.states.admin_products import (
    ProductCreateState,
    ProductEditState,
    ProductQuestionCreateState,
)
from app.core.config import get_settings
from app.core.enums import ProductQuestionType
from app.services.config_service import ConfigService
from app.services.product_admin_service import (
    ProductAdminService,
    ProductInput,
    ProductNotFoundError,
    ProductQuestionNotFoundError,
    ProductValidationError,
    QuestionInput,
)

router = Router(name="admin_products")


def _format_products_text(products: Sequence) -> str:
    if not products:
        return "No products defined yet. Use the button below to add your first product."

    lines = ["<b>Products</b>"]
    for index, product in enumerate(products, start=1):
        status = "ACTIVE" if product.is_active else "INACTIVE"
        lines.append(
            f"{index}. {html.escape(product.name)} - {status}\n"
            f"   Price: {format_price(product.price)} {product.currency}"
        )
    return "\n".join(lines)


def _format_product_details(product) -> str:
    summary = html.escape(product.summary) if product.summary else "-"
    description = html.escape(product.description) if product.description else "-"
    inventory = "Unlimited" if product.inventory is None else str(product.inventory)
    status = "Active" if product.is_active else "Inactive"
    question_count = len(product.questions or [])

    return (
        f"<b>{html.escape(product.name)}</b>\n"
        f"Status: {status}\n"
        f"Price: {format_price(product.price)} {product.currency}\n"
        f"Inventory: {inventory}\n"
        f"Position: {product.position}\n\n"
        f"<b>Summary</b>\n{summary}\n\n"
        f"<b>Description</b>\n{description}\n\n"
        f"Questions configured: {question_count}"
    )


def _format_questions_text(questions: Iterable) -> str:
    questions = list(questions)
    if not questions:
        return "No questions configured yet. Use the button below to add one."

    lines: list[str] = ["<b>Purchase form questions</b>"]
    for index, question in enumerate(questions, start=1):
        required = "REQUIRED" if question.is_required else "OPTIONAL"
        base = (
            f"{index}. <code>{html.escape(question.field_key)}</code>"
            f" - {question.question_type.value} ({required})"
        )
        prompt = html.escape(question.prompt)
        lines.append(f"{base}\n   {prompt}")
        if question.config and question.config.get("options"):
            options = ", ".join(html.escape(opt) for opt in question.config["options"])
            lines.append(f"   Options: {options}")
        if question.help_text:
            lines.append(f"   Help: {html.escape(question.help_text)}")
    return "\n".join(lines)


def format_price(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01")) if value.as_tuple().exponent < -2 else value
    text = format(normalized, "f").rstrip("0").rstrip(".")
    return text or "0"


def _parse_decimal(value: str) -> Decimal:
    candidate = value.strip().replace(",", ".")
    try:
        result = Decimal(candidate)
    except InvalidOperation as exc:
        raise ProductValidationError("Enter a valid decimal number.") from exc
    if result <= 0:
        raise ProductValidationError("Price must be greater than zero.")
    return result.quantize(Decimal("0.01"))


def _parse_integer(value: str, *, allow_zero: bool = True) -> int:
    try:
        result = int(value.strip())
    except ValueError as exc:
        raise ProductValidationError("Enter a valid integer number.") from exc
    if not allow_zero and result <= 0:
        raise ProductValidationError("Value must be positive.")
    if allow_zero and result < 0:
        raise ProductValidationError("Value cannot be negative.")
    return result


def _normalize_field_key(value: str) -> str:
    candidate = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,49}", candidate):
        raise ProductValidationError(
            "Field key must start with a letter and contain 3-50 lowercase letters, numbers or underscores."
        )
    return candidate


def _is_skip_message(message: Message) -> bool:
    return message.text is not None and message.text.strip().lower() in {"/skip", "skip"}


def _is_cancel_message(message: Message) -> bool:
    return message.text is not None and message.text.strip().lower() in {"/cancel", "cancel"}




def _field_prompt(field: str) -> str:
    prompts = {
        "name": "Enter new product name. Send /cancel to abort.",
        "summary": "Enter new summary. Send /skip to clear it or /cancel to abort.",
        "description": "Enter new description. Send /skip to clear it or /cancel to abort.",
        "price": "Enter new price (decimal number).",
        "currency": "Enter currency code (3 letters).",
        "inventory": "Enter inventory quantity (integer). Send /skip for unlimited.",
        "position": "Enter display position (positive integer).",
    }
    try:
        return prompts[field]
    except KeyError as exc:
        raise ValueError(f"Unsupported field '{field}'") from exc


async def _cancel_state(message: Message, state: FSMContext, notice: str) -> None:
    await state.clear()
    await message.answer(notice)


def _parse_edit_value(field: str, value: str) -> tuple[object | None, bool]:
    normalized = value.strip()

    if field == "name":
        if not normalized:
            raise ProductValidationError("Name cannot be empty.")
        return normalized, False

    if field in {"summary", "description"}:
        if not normalized or _is_skip_message_value(normalized):
            return None, True
        return normalized, False

    if field == "price":
        return _parse_decimal(normalized), False

    if field == "currency":
        candidate = normalized.upper()
        if not re.fullmatch(r"[A-Z]{3}", candidate):
            raise ProductValidationError("Currency must be a 3-letter ISO code (e.g. USD).")
        return candidate, False

    if field == "inventory":
        if not normalized or _is_skip_message_value(normalized):
            return None, True
        return _parse_integer(normalized, allow_zero=True), False

    if field == "position":
        if not normalized:
            raise ProductValidationError("Position must be a positive integer.")
        return _parse_integer(normalized, allow_zero=False), False

    raise ProductValidationError("Unsupported field.")


async def _safe_edit_message(
    message: Message, text: str, *, reply_markup: object | None = None
) -> None:
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        details = (exc.message or "").lower()
        if "message is not modified" not in details:
            raise


def _is_skip_message_value(value: str) -> bool:
    return value.strip().lower() in {"/skip", "skip"}
# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

async def render_products_overview(
    message: Message,
    session: AsyncSession,
    *,
    as_new_message: bool = False,
) -> None:
    service = ProductAdminService(session)
    products = await service.list_products()
    text = _format_products_text(products)
    markup = products_overview_keyboard(products)

    if as_new_message:
        await message.answer(text, reply_markup=markup)
    else:
        await _safe_edit_message(message, text, reply_markup=markup)


async def render_product_details(
    message: Message,
    session: AsyncSession,
    product_id: int,
    *,
    as_new_message: bool = False,
) -> None:
    service = ProductAdminService(session)
    product = await service.get_product(product_id)
    text = _format_product_details(product)
    markup = product_detail_keyboard(product)

    if as_new_message:
        await message.answer(text, reply_markup=markup)
    else:
        await _safe_edit_message(message, text, reply_markup=markup)


async def render_questions_overview(
    message: Message,
    session: AsyncSession,
    product_id: int,
    *,
    as_new_message: bool = False,
) -> None:
    service = ProductAdminService(session)
    product = await service.get_product(product_id)
    questions = await service.list_questions(product_id)

    text = _format_questions_text(questions)
    markup = product_questions_keyboard(product_id, questions)

    header = f"<b>{html.escape(product.name)}</b> - form builder\n\n"
    payload = header + text

    if as_new_message:
        await message.answer(payload, reply_markup=markup)
    else:
        await _safe_edit_message(message, payload, reply_markup=markup)


async def _return_to_admin_menu(message: Message, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    enabled = await config_service.subscription_required()
    await _safe_edit_message(
        message,
        "Admin control panel: manage subscription gates, channels, products, and orders.",
        reply_markup=admin_menu_keyboard(subscription_enabled=enabled),
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

@router.callback_query(F.data == AdminMenuCallback.MANAGE_PRODUCTS.value)
async def open_products(callback: CallbackQuery, session: AsyncSession) -> None:
    await render_products_overview(callback.message, session, as_new_message=False)
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "back_to_admin"))
async def back_to_admin(callback: CallbackQuery, session: AsyncSession) -> None:
    await _return_to_admin_menu(callback.message, session)
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "back_to_list"))
async def back_to_list(callback: CallbackQuery, session: AsyncSession) -> None:
    await render_products_overview(callback.message, session, as_new_message=False)
    await callback.answer()
# ---------------------------------------------------------------------------
# Product creation wizard
# ---------------------------------------------------------------------------

@router.callback_query(ProductAdminCallback.filter(F.action == "add"))
async def start_create_product(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is not None:
        await callback.answer("Finish the current operation first.", show_alert=True)
        return
    await state.set_state(ProductCreateState.name)
    await callback.message.answer(
        "Enter product name.\nSend /cancel to abort creation.",
    )
    await callback.answer()


@router.message(ProductCreateState.name)
async def collect_product_name(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Product creation cancelled.")
        return
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("Name cannot be empty. Please enter product name.")
        return
    await state.update_data(name=name)
    await state.set_state(ProductCreateState.summary)
    await message.answer("Enter summary (optional). Send /skip to leave empty.")


@router.message(ProductCreateState.summary)
async def collect_product_summary(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Product creation cancelled.")
        return
    if _is_skip_message(message):
        await state.update_data(summary=None)
    else:
        await state.update_data(summary=message.text.strip())
    await state.set_state(ProductCreateState.description)
    await message.answer("Enter full description (optional). Send /skip to leave empty.")


@router.message(ProductCreateState.description)
async def collect_product_description(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Product creation cancelled.")
        return
    if _is_skip_message(message):
        await state.update_data(description=None)
    else:
        await state.update_data(description=message.text.strip())
    await state.set_state(ProductCreateState.price)
    await message.answer("Enter price (decimal number).")


@router.message(ProductCreateState.price)
async def collect_product_price(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Product creation cancelled.")
        return
    try:
        price = _parse_decimal(message.text or "")
    except ProductValidationError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(price=price)
    await state.set_state(ProductCreateState.currency)
    default_currency = get_settings().payment_currency
    await message.answer(
        f"Enter currency code (3 letters). Send /skip to use default {default_currency}.",
    )


@router.message(ProductCreateState.currency)
async def collect_product_currency(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Product creation cancelled.")
        return
    if _is_skip_message(message):
        currency = get_settings().payment_currency
    else:
        currency = (message.text or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            await message.answer("Currency must be a 3-letter ISO code (e.g. USD).")
            return
    await state.update_data(currency=currency)
    await state.set_state(ProductCreateState.inventory)
    await message.answer("Enter inventory quantity (integer). Send /skip for unlimited.")


@router.message(ProductCreateState.inventory)
async def collect_product_inventory(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Product creation cancelled.")
        return
    if _is_skip_message(message):
        inventory = None
    else:
        try:
            inventory = _parse_integer(message.text or "", allow_zero=True)
        except ProductValidationError as exc:
            await message.answer(str(exc))
            return
    await state.update_data(inventory=inventory)
    await state.set_state(ProductCreateState.position)
    await message.answer("Enter display position (integer). Send /skip to assign automatically.")


@router.message(ProductCreateState.position)
async def collect_product_position(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Product creation cancelled.")
        return
    if _is_skip_message(message):
        position = None
    else:
        try:
            position = _parse_integer(message.text or "", allow_zero=False)
        except ProductValidationError as exc:
            await message.answer(str(exc))
            return
    await state.update_data(position=position)
    data = await state.get_data()
    text = (
        "<b>Review product details</b>\n\n"
        f"Name: {html.escape(data['name'])}\n"
        f"Price: {format_price(data['price'])} {data['currency']}\n"
        f"Inventory: {'Unlimited' if data.get('inventory') is None else data['inventory']}\n"
        f"Position: {data.get('position', 'Auto')}\n"
        f"Summary: {html.escape(data.get('summary') or '-') }\n"
        f"Description: {html.escape(data.get('description') or '-') }"
    )
    await state.set_state(ProductCreateState.confirm)
    await message.answer(text, reply_markup=creation_confirm_keyboard())


@router.callback_query(ProductAdminCallback.filter(F.action == "create_cancel"))
async def cancel_product_creation(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != ProductCreateState.confirm.state:
        await callback.answer()
        return
    await state.clear()
    await _safe_edit_message(callback.message, "Product creation aborted.")
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "create_confirm"))
async def confirm_product_creation(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if await state.get_state() != ProductCreateState.confirm.state:
        await callback.answer()
        return
    data = await state.get_data()
    await state.clear()
    service = ProductAdminService(session)
    product_input = ProductInput(
        name=data['name'],
        summary=data.get('summary'),
        description=data.get('description'),
        price=data['price'],
        currency=data['currency'],
        inventory=data.get('inventory'),
        position=data.get('position'),
    )
    product = await service.create_product(product_input)
    await _safe_edit_message(callback.message, "Product created successfully.")
    await render_product_details(callback.message, session, product.id, as_new_message=True)
    await callback.answer("Product saved")
# ---------------------------------------------------------------------------
# Product editing and status management
# ---------------------------------------------------------------------------

@router.callback_query(ProductAdminCallback.filter(F.action == "edit_menu"))
async def open_edit_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    service = ProductAdminService(session)
    try:
        product = await service.get_product(product_id)
    except ProductNotFoundError:
        await callback.answer("Product not found", show_alert=True)
        await render_products_overview(callback.message, session, as_new_message=False)
        return
    await _safe_edit_message(
        callback.message,
        "Select the field you want to update.",
        reply_markup=product_edit_fields_keyboard(product.id),
    )
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "edit_field"))
async def select_field_to_edit(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is not None:
        await callback.answer("Finish the current operation first.", show_alert=True)
        return
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    field = data.value
    await state.set_state(ProductEditState.awaiting_value)
    await state.update_data(product_id=product_id, field=field)
    prompt = _field_prompt(field)
    await callback.message.answer(prompt)
    await callback.answer()


@router.message(ProductEditState.awaiting_value)
async def apply_field_edit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Edit cancelled.")
        return

    data = await state.get_data()
    product_id = data['product_id']
    field = data['field']
    raw_value = message.text or ""

    try:
        parsed_value, cleared = _parse_edit_value(field, raw_value)
    except ProductValidationError as exc:
        await message.answer(str(exc))
        return

    service = ProductAdminService(session)
    update_payload: dict[str, object | None] = {field: parsed_value}
    if cleared:
        update_payload[field] = None

    try:
        product = await service.update_product(product_id, **update_payload)
    except ProductNotFoundError:
        await message.answer("Product no longer exists.")
        await state.clear()
        return

    await message.answer("Field updated.")
    await state.clear()
    await render_product_details(message, session, product.id, as_new_message=True)


@router.callback_query(ProductAdminCallback.filter(F.action == "view"))
async def view_product(callback: CallbackQuery, session: AsyncSession) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    try:
        await render_product_details(callback.message, session, product_id, as_new_message=False)
    except ProductNotFoundError:
        await callback.answer("Product no longer exists", show_alert=True)
        await render_products_overview(callback.message, session, as_new_message=False)
        return
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "toggle"))
async def toggle_product(callback: CallbackQuery, session: AsyncSession) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    service = ProductAdminService(session)
    try:
        product = await service.toggle_product_active(product_id)
    except ProductNotFoundError:
        await callback.answer("Product no longer exists", show_alert=True)
        await render_products_overview(callback.message, session, as_new_message=False)
        return
    await callback.answer("Status updated")
    await render_product_details(callback.message, session, product.id, as_new_message=False)


@router.callback_query(ProductAdminCallback.filter(F.action == "delete"))
async def confirm_delete_product(callback: CallbackQuery) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    text = "Are you sure you want to delete this product? This action cannot be undone."
    await _safe_edit_message(
        callback.message,
        text,
        reply_markup=product_delete_confirm_keyboard(product_id),
    )
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "delete_confirm"))
async def delete_product(callback: CallbackQuery, session: AsyncSession) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    service = ProductAdminService(session)
    try:
        await service.delete_product(product_id)
    except ProductNotFoundError:
        await callback.answer("Product not found", show_alert=True)
    else:
        await callback.answer("Product deleted")
    await render_products_overview(callback.message, session, as_new_message=False)
# ---------------------------------------------------------------------------
# Question management
# ---------------------------------------------------------------------------

@router.callback_query(ProductAdminCallback.filter(F.action == "questions"))
async def manage_questions(callback: CallbackQuery, session: AsyncSession) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    try:
        await render_questions_overview(callback.message, session, product_id, as_new_message=False)
    except ProductNotFoundError:
        await callback.answer("Product not found", show_alert=True)
        await render_products_overview(callback.message, session, as_new_message=False)
        return
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "question_delete"))
async def confirm_delete_question(callback: CallbackQuery) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    question_id = int(data.question_id)
    await _safe_edit_message(
        callback.message,
        "Delete this question?",
        reply_markup=question_delete_confirm_keyboard(product_id, question_id),
    )
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "question_delete_confirm"))
async def delete_question(callback: CallbackQuery, session: AsyncSession) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    question_id = int(data.question_id)
    service = ProductAdminService(session)
    try:
        await service.delete_question(question_id)
    except ProductQuestionNotFoundError:
        await callback.answer("Question not found", show_alert=True)
    else:
        await callback.answer("Question removed")
    await render_questions_overview(callback.message, session, product_id, as_new_message=False)


@router.callback_query(ProductAdminCallback.filter(F.action == "question_add"))
async def start_question_creation(callback: CallbackQuery, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is not None:
        await callback.answer("Finish the current operation first.", show_alert=True)
        return
    data = ProductAdminCallback.unpack(callback.data)
    product_id = int(data.product_id)
    await state.set_state(ProductQuestionCreateState.field_key)
    await state.update_data(product_id=product_id)
    await callback.message.answer(
        "Enter a field key for this question. Use lowercase letters, digits and underscores.\nSend /cancel to abort.",
    )
    await callback.answer()


@router.message(ProductQuestionCreateState.field_key)
async def collect_question_field_key(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Question creation cancelled.")
        return
    try:
        field_key = _normalize_field_key(message.text or "")
    except ProductValidationError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(field_key=field_key)
    await state.set_state(ProductQuestionCreateState.prompt)
    await message.answer("Enter the question prompt shown to the user.")


@router.message(ProductQuestionCreateState.prompt)
async def collect_question_prompt(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Question creation cancelled.")
        return
    prompt = message.text.strip() if message.text else ""
    if not prompt:
        await message.answer("Prompt cannot be empty.")
        return
    await state.update_data(prompt=prompt)
    await state.set_state(ProductQuestionCreateState.help_text)
    await message.answer("Enter optional help text. Send /skip to leave empty.")


@router.message(ProductQuestionCreateState.help_text)
async def collect_question_help(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Question creation cancelled.")
        return
    if _is_skip_message(message):
        help_text = None
    else:
        help_text = message.text.strip()
    await state.update_data(help_text=help_text)
    data = await state.get_data()
    await state.set_state(ProductQuestionCreateState.question_type)
    await message.answer(
        "Select question type.",
        reply_markup=question_type_keyboard(data["product_id"]),
    )


@router.callback_query(
    ProductAdminCallback.filter(F.action == "question_type_set"),
    ProductQuestionCreateState.question_type,
)
async def set_question_type(callback: CallbackQuery, state: FSMContext) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    question_type = ProductQuestionType(data.value)
    await state.update_data(question_type=question_type)
    await state.set_state(ProductQuestionCreateState.required)
    await _safe_edit_message(
        callback.message,
        "Should this question be required?",
        reply_markup=question_required_keyboard(int(data.product_id)),
    )
    await callback.answer()


@router.callback_query(
    ProductAdminCallback.filter(F.action == "question_required_set"),
    ProductQuestionCreateState.required,
)
async def set_question_required(callback: CallbackQuery, state: FSMContext) -> None:
    data = ProductAdminCallback.unpack(callback.data)
    is_required = data.value == "true"
    await state.update_data(is_required=is_required)

    stored = await state.get_data()
    question_type: ProductQuestionType = stored["question_type"]
    if question_type in {ProductQuestionType.SELECT, ProductQuestionType.MULTISELECT}:
        await state.set_state(ProductQuestionCreateState.options)
        await _safe_edit_message(callback.message, "Provide answer options separated by commas.")
    else:
        await _finalize_question_summary(callback.message, state)
    await callback.answer()


@router.message(ProductQuestionCreateState.options)
async def collect_question_options(message: Message, state: FSMContext) -> None:
    if _is_cancel_message(message):
        await _cancel_state(message, state, "Question creation cancelled.")
        return
    raw = (message.text or "").strip()
    options = [item.strip() for item in raw.split(",") if item.strip()]
    if len(options) < 2:
        await message.answer("Provide at least two options separated by commas.")
        return
    await state.update_data(config={"options": options})
    await _finalize_question_summary(message, state)


async def _finalize_question_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    question_type: ProductQuestionType = data["question_type"]
    lines = [
        "<b>Review question</b>",
        f"Field key: <code>{html.escape(data['field_key'])}</code>",
        f"Prompt: {html.escape(data['prompt'])}",
        f"Type: {question_type.value}",
        f"Required: {'yes' if data['is_required'] else 'no'}",
    ]
    if data.get("help_text"):
        lines.append(f"Help: {html.escape(data['help_text'])}")
    if data.get("config") and data["config"].get("options"):
        options = ", ".join(html.escape(opt) for opt in data["config"]["options"])
        lines.append(f"Options: {options}")

    await state.set_state(ProductQuestionCreateState.confirm)
    await message.answer(
        "\n".join(lines),
        reply_markup=question_creation_confirm_keyboard(data["product_id"]),
    )


@router.callback_query(ProductAdminCallback.filter(F.action == "question_create_cancel"))
async def cancel_question_creation(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    product_id = data.get("product_id")
    await state.clear()
    await _safe_edit_message(callback.message, "Question creation aborted.")
    if product_id is not None:
        await render_questions_overview(callback.message, session, int(product_id), as_new_message=True)
    await callback.answer()


@router.callback_query(ProductAdminCallback.filter(F.action == "question_create_confirm"))
async def confirm_question_creation(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if await state.get_state() != ProductQuestionCreateState.confirm.state:
        await callback.answer()
        return
    data = await state.get_data()
    await state.clear()
    service = ProductAdminService(session)
    question_input = QuestionInput(
        product_id=data["product_id"],
        field_key=data["field_key"],
        prompt=data["prompt"],
        help_text=data.get("help_text"),
        question_type=data["question_type"],
        is_required=data["is_required"],
        config=data.get("config"),
    )
    try:
        question = await service.add_question(question_input)
    except ProductValidationError as exc:
        await callback.answer(str(exc), show_alert=True)
        await render_questions_overview(callback.message, session, data["product_id"], as_new_message=True)
        return
    except LookupError:
        await callback.answer("Could not save question. Please try again.", show_alert=True)
        await render_questions_overview(callback.message, session, data["product_id"], as_new_message=True)
        return
    await _safe_edit_message(callback.message, "Question added successfully.")
    await render_questions_overview(callback.message, session, question.product_id, as_new_message=True)
    await callback.answer("Question saved")


@router.callback_query(
    ProductAdminCallback.filter(F.action == "question_type_set"),
    ~StateFilter(ProductQuestionCreateState.question_type),
)
async def ignore_unexpected_type_selection(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(
    ProductAdminCallback.filter(
        F.action.in_({"question_required_set", "question_create_confirm", "question_create_cancel"})
    ),
    ~StateFilter(ProductQuestionCreateState),
)
async def ignore_unexpected_question_callbacks(callback: CallbackQuery) -> None:
    await callback.answer()
