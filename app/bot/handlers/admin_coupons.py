from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Sequence

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    ADMIN_COUPON_TOGGLE_PREFIX,
    ADMIN_COUPON_VIEW_PREFIX,
    ADMIN_COUPON_DELETE_PREFIX,
    ADMIN_COUPON_DELETE_CONFIRM_PREFIX,
    ADMIN_COUPON_EDIT_FIELD_PREFIX,
    ADMIN_COUPON_EDIT_MENU_PREFIX,
    ADMIN_COUPON_EDIT_TYPE_PREFIX,
    ADMIN_COUPON_TOGGLE_AUTO_PREFIX,
    ADMIN_COUPON_USAGE_PREFIX,
    AdminCouponCallback,
    AdminMenuCallback,
    coupon_dashboard_keyboard,
    coupon_details_keyboard,
    coupon_edit_keyboard,
    coupon_delete_confirm_keyboard,
    coupon_usage_keyboard,
)
from app.bot.states.admin_coupon import AdminCouponState
from app.core.enums import CouponStatus, CouponType
from app.infrastructure.db.models import Coupon
from app.infrastructure.db.repositories import CouponRepository
from app.services.coupon_service import CouponService

router = Router(name="admin_coupons")

COUPON_TYPES = {
    "fixed": CouponType.FIXED,
    "percent": CouponType.PERCENT,
    "shipping": CouponType.SHIPPING,
}

COUPON_TYPE_LABELS = {
    CouponType.FIXED: "Fixed amount",
    CouponType.PERCENT: "Percent",
    CouponType.SHIPPING: "Shipping credit",
}

MONEY_QUANT = Decimal("0.01")


@router.callback_query(F.data == AdminMenuCallback.MANAGE_COUPONS.value)
async def handle_manage_coupons(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_coupons_overview(callback.message, session)
    await callback.answer()


@router.callback_query(F.data == AdminCouponCallback.REFRESH.value)
async def handle_refresh_coupons(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _render_coupons_overview(callback.message, session)
    await callback.answer("Coupons refreshed")


@router.callback_query(F.data == AdminCouponCallback.CREATE.value)
async def handle_create_coupon(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminCouponState.create_code)
    await callback.message.answer(
        "Enter a unique coupon code (letters/numbers). Send /cancel to abort."
    )
    await callback.answer()


@router.message(AdminCouponState.create_code)
async def process_coupon_code(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await state.clear()
        await message.answer("Coupon creation cancelled.")
        return
    if not text:
        await message.answer("Coupon code cannot be empty. Try again or send /cancel.")
        return
    code = text.upper()

    repo = CouponRepository(session)
    existing = await repo.get_by_code(code, with_relations=False)
    if existing:
        await message.answer("This code already exists. Choose a different code.")
        return

    await state.update_data(code=code)
    await state.set_state(AdminCouponState.create_name)
    await message.answer("Enter coupon name/label (optional). Send /skip to leave blank or /cancel.")


@router.message(AdminCouponState.create_name)
async def process_coupon_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await state.clear()
        await message.answer("Coupon creation cancelled.")
        return

    name = None if text.lower() == "/skip" else text
    await state.update_data(name=name)
    await state.set_state(AdminCouponState.create_type)
    await message.answer(
        "Select coupon type:",
        reply_markup=_coupon_type_keyboard(),
    )


@router.callback_query(AdminCouponState.create_type, F.data.startswith("admin:coupon:type:"))
async def process_coupon_type(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.removeprefix("admin:coupon:type:").lower()
    coupon_type = COUPON_TYPES.get(key)
    if coupon_type is None:
        await callback.answer("Unknown type.", show_alert=True)
        return
    await state.update_data(coupon_type=coupon_type.value)
    await state.set_state(AdminCouponState.create_value)
    if coupon_type == CouponType.PERCENT:
        await callback.message.answer(
            "Enter discount percentage (e.g., 15 for 15%). Send /cancel to abort."
        )
    else:
        await callback.message.answer(
            "Enter discount amount (e.g., 5.50). Send /cancel to abort."
        )
    await callback.answer()


@router.message(AdminCouponState.create_value)
async def process_coupon_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await state.clear()
        await message.answer("Coupon creation cancelled.")
        return
    data = await state.get_data()
    coupon_type = CouponType(data.get("coupon_type"))
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        await message.answer("Enter a valid number (e.g., 10 or 5.75).")
        return

    if coupon_type == CouponType.PERCENT:
        if value <= 0 or value > 100:
            await message.answer("Percentage must be between 0 and 100.")
            return
        await state.update_data(percentage=str(value), amount=None)
    else:
        if value <= 0:
            await message.answer("Amount must be greater than zero.")
            return
        await state.update_data(amount=str(value), percentage=None)

    await state.set_state(AdminCouponState.create_min_total)
    await message.answer(
        "Enter minimum order total required (optional). Send a number or /skip. /cancel to abort."
    )


@router.message(AdminCouponState.create_min_total)
async def process_coupon_min_total(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await state.clear()
        await message.answer("Coupon creation cancelled.")
        return
    if text.lower() in {"/skip", ""}:
        min_total = None
    else:
        try:
            min_total = Decimal(text)
        except (InvalidOperation, ValueError):
            await message.answer("Enter a valid number or /skip.")
            return
        if min_total < 0:
            await message.answer("Minimum total cannot be negative.")
            return

    await state.update_data(min_order_total=str(min_total) if min_total is not None else None)
    await state.set_state(AdminCouponState.create_max_redemptions)
    await message.answer(
        "Enter maximum total redemptions (optional). Send an integer or /skip. /cancel to abort."
    )


@router.message(AdminCouponState.create_max_redemptions)
async def process_coupon_max_redemptions(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await state.clear()
        await message.answer("Coupon creation cancelled.")
        return
    if text.lower() in {"/skip", ""}:
        max_redemptions = None
    else:
        if not text.isdigit():
            await message.answer("Enter a positive integer or /skip.")
            return
        max_redemptions = int(text)
        if max_redemptions <= 0:
            await message.answer("Value must be greater than zero.")
            return

    await state.update_data(max_redemptions=max_redemptions)
    await state.set_state(AdminCouponState.create_per_user_limit)
    await message.answer(
        "Enter per-user redemption limit (optional). Send an integer or /skip. /cancel to abort."
    )


@router.message(AdminCouponState.create_per_user_limit)
async def process_coupon_per_user_limit(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await state.clear()
        await message.answer("Coupon creation cancelled.")
        return
    if text.lower() in {"/skip", ""}:
        per_user_limit = None
    else:
        if not text.isdigit():
            await message.answer("Enter a positive integer or /skip.")
            return
        per_user_limit = int(text)
        if per_user_limit <= 0:
            await message.answer("Value must be greater than zero.")
            return

    data = await state.get_data()
    coupon = Coupon(
        code=data["code"],
        name=data.get("name"),
        coupon_type=CouponType(data["coupon_type"]),
        status=CouponStatus.ACTIVE,
        amount=Decimal(data["amount"]) if data.get("amount") else None,
        percentage=Decimal(data["percentage"]) if data.get("percentage") else None,
        min_order_total=Decimal(data["min_order_total"]) if data.get("min_order_total") else None,
        max_redemptions=data.get("max_redemptions"),
        per_user_limit=per_user_limit,
        auto_apply=False,
    )
    service = CouponService(session)
    await service.create_coupon(coupon)
    await state.clear()

    await message.answer(
        f"Coupon <b>{coupon.code}</b> created and activated."
    )

    await _render_coupons_overview(message, session, notice=f"Coupon {coupon.code} created.")


@router.callback_query(F.data.startswith(ADMIN_COUPON_VIEW_PREFIX))
async def handle_coupon_view(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_VIEW_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    if await _render_coupon_detail(callback.message, session, coupon_id, state=state):
        await callback.answer()
    else:
        await callback.answer("Coupon not found.", show_alert=True)


@router.callback_query(F.data.startswith(ADMIN_COUPON_TOGGLE_PREFIX))
async def handle_coupon_toggle(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_TOGGLE_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    service = CouponService(session)
    if coupon.status == CouponStatus.ACTIVE:
        await service.deactivate_coupon(coupon)
        notice = "Coupon deactivated."
    else:
        coupon.status = CouponStatus.ACTIVE
        await session.flush()
        notice = "Coupon activated."

    await _render_coupon_detail(callback.message, session, coupon.id, state=state, notice=notice)
    await callback.answer(notice)


@router.callback_query(F.data.startswith(ADMIN_COUPON_TOGGLE_AUTO_PREFIX))
async def handle_coupon_toggle_auto(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_TOGGLE_AUTO_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    coupon.auto_apply = not bool(coupon.auto_apply)
    await session.flush()
    notice = f"Auto-apply {'enabled' if coupon.auto_apply else 'disabled'}."
    await _render_coupon_detail(callback.message, session, coupon.id, state=state, notice=notice)
    await callback.answer(notice)


@router.callback_query(F.data.startswith(ADMIN_COUPON_EDIT_MENU_PREFIX))
async def handle_coupon_edit_menu(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_EDIT_MENU_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    await _store_detail_context(state, callback.message, coupon.id)
    lines = [
        f"<b>Edit coupon {coupon.code}</b>",
        f"Current type: {COUPON_TYPE_LABELS.get(coupon.coupon_type, coupon.coupon_type.value)}",
        f"Value: {_describe_coupon_value(coupon)}",
        "",
        "Select the field you want to change.",
    ]
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=coupon_edit_keyboard(coupon),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_COUPON_USAGE_PREFIX))
async def handle_coupon_usage(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_USAGE_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    usage = await CouponService(session).usage_summary(coupon, recent_limit=10)
    text = _format_coupon_usage(coupon, usage)
    await callback.message.edit_text(
        text,
        reply_markup=coupon_usage_keyboard(coupon.id),
        disable_web_page_preview=True,
    )
    await _store_detail_context(state, callback.message, coupon.id)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_COUPON_DELETE_PREFIX))
async def handle_coupon_delete_request(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_DELETE_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    await _store_detail_context(state, callback.message, coupon.id)
    await callback.message.edit_text(
        "\n".join(
            [
                f"<b>Delete coupon {coupon.code}</b>",
                "This will remove the coupon and all redemption history.",
                "Are you sure you want to continue?",
            ]
        ),
        reply_markup=coupon_delete_confirm_keyboard(coupon.id),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_COUPON_DELETE_CONFIRM_PREFIX))
async def handle_coupon_delete_confirm(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_DELETE_CONFIRM_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    code = coupon.code
    await CouponService(session).delete_coupon(coupon)
    await state.update_data(
        coupon_detail_chat=None,
        coupon_detail_message=None,
        coupon_detail_coupon_id=None,
        edit_coupon_id=None,
    )
    await _render_coupons_overview(callback.message, session, notice=f"Coupon {code} deleted.")
    await callback.answer("Coupon deleted.")


@router.callback_query(F.data.startswith(ADMIN_COUPON_EDIT_FIELD_PREFIX))
async def handle_coupon_edit_field(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    payload = callback.data.removeprefix(ADMIN_COUPON_EDIT_FIELD_PREFIX)
    try:
        field, raw_id = payload.split(":", 1)
        coupon_id = int(raw_id)
    except ValueError:
        await callback.answer("Invalid request.", show_alert=True)
        return

    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    await _store_detail_context(state, callback.message, coupon.id)
    await state.update_data(edit_coupon_id=coupon.id)

    if field == "name":
        await state.set_state(AdminCouponState.edit_name)
        await callback.message.answer(
            f"Current name: {coupon.name or '-'}\n"
            "Send the new coupon name.\n"
            "Use /clear to remove the name or /cancel to abort."
        )
    elif field == "description":
        await state.set_state(AdminCouponState.edit_description)
        await callback.message.answer(
            f"Current description: {coupon.description or '-'}\n"
            "Send the new description.\n"
            "Use /clear to remove it or /cancel to abort."
        )
    elif field == "value":
        await state.set_state(AdminCouponState.edit_value)
        prompt = (
            "Send the discount percentage (between 0 and 100)."
            if coupon.coupon_type == CouponType.PERCENT
            else "Send the discount amount (e.g., 5.50)."
        )
        await callback.message.answer(f"{prompt}\nSend /cancel to abort.")
    elif field == "min_total":
        await state.set_state(AdminCouponState.edit_min_total)
        await callback.message.answer(
            f"Current minimum order: {coupon.min_order_total or '-'}\n"
            "Send the new minimum order total.\n"
            "Use /clear to remove the requirement or /cancel to abort."
        )
    elif field == "max_discount":
        await state.set_state(AdminCouponState.edit_max_discount)
        await callback.message.answer(
            f"Current maximum discount: {coupon.max_discount_amount or '-'}\n"
            "Send the new maximum discount amount.\n"
            "Use /clear to remove the cap or /cancel to abort."
        )
    elif field == "max_redemptions":
        await state.set_state(AdminCouponState.edit_max_redemptions)
        await callback.message.answer(
            f"Current total redemption limit: {coupon.max_redemptions or '-'}\n"
            "Send the new total redemption limit (integer).\n"
            "Use /clear to remove the limit or /cancel to abort."
        )
    elif field == "per_user_limit":
        await state.set_state(AdminCouponState.edit_per_user_limit)
        await callback.message.answer(
            f"Current per-user limit: {coupon.per_user_limit or '-'}\n"
            "Send the new per-user limit (integer).\n"
            "Use /clear to remove the limit or /cancel to abort."
        )
    elif field == "start_at":
        await state.set_state(AdminCouponState.edit_start_at)
        await callback.message.answer(
            f"Current start date: {_format_dt(coupon.start_at)}\n"
            "Send the new start date/time in UTC (e.g., 2025-03-01 12:30).\n"
            "Use /clear to remove the start date or /cancel to abort."
        )
    elif field == "end_at":
        await state.set_state(AdminCouponState.edit_end_at)
        await callback.message.answer(
            f"Current end date: {_format_dt(coupon.end_at)}\n"
            "Send the new end date/time in UTC (e.g., 2025-03-15 23:59).\n"
            "Use /clear to remove the end date or /cancel to abort."
        )
    else:
        await callback.answer("Unsupported field.", show_alert=True)
        return

    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_COUPON_EDIT_TYPE_PREFIX))
async def handle_coupon_edit_type_request(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    coupon_id = _extract_coupon_id(callback.data, ADMIN_COUPON_EDIT_TYPE_PREFIX)
    if coupon_id is None:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return

    await _store_detail_context(state, callback.message, coupon.id)
    await state.update_data(edit_coupon_id=coupon.id)
    await state.set_state(AdminCouponState.edit_type)
    await callback.message.answer(
        "Select the new coupon type:",
        reply_markup=_coupon_type_keyboard(),
    )
    await callback.answer()


@router.callback_query(AdminCouponState.edit_type, F.data.startswith("admin:coupon:type:"))
async def handle_coupon_type_selection(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    key = callback.data.removeprefix("admin:coupon:type:").lower()
    coupon_type = COUPON_TYPES.get(key)
    if coupon_type is None:
        await callback.answer("Unknown type.", show_alert=True)
        return

    data = await state.get_data()
    coupon_id = data.get("edit_coupon_id")
    if not coupon_id:
        await state.set_state(None)
        await callback.answer("Coupon context lost.", show_alert=True)
        return

    repo = CouponRepository(session)
    coupon = await repo.get_by_id(int(coupon_id))
    if coupon is None:
        await state.set_state(None)
        await callback.answer("Coupon not found.", show_alert=True)
        return

    coupon.coupon_type = coupon_type
    if coupon_type == CouponType.PERCENT:
        coupon.amount = None
    else:
        coupon.percentage = None
    await session.flush()

    await state.set_state(AdminCouponState.edit_value)
    await callback.message.answer(
        "Coupon type updated. Send the new value now.\n"
        + (
            "Enter percentage between 0 and 100."
            if coupon_type == CouponType.PERCENT
            else "Enter the discount amount (e.g., 5.50)."
        )
        + "\nSend /cancel to abort."
    )
    await callback.answer("Type updated. Provide the new value.")


@router.message(AdminCouponState.edit_name)
async def process_edit_name(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Name update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    if _is_clear(text) or not text:
        coupon.name = None
        notice = "Coupon name cleared."
    else:
        if len(text) > 128:
            await message.answer("Name must be at most 128 characters.")
            return
        coupon.name = text
        notice = "Coupon name updated."

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


@router.message(AdminCouponState.edit_description)
async def process_edit_description(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Description update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    if _is_clear(text) or not text:
        coupon.description = None
        notice = "Coupon description cleared."
    else:
        if len(text) > 512:
            await message.answer("Description must be at most 512 characters.")
            return
        coupon.description = text
        notice = "Coupon description updated."

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


@router.message(AdminCouponState.edit_value)
async def process_edit_value(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Value update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        await message.answer("Enter a valid number (e.g., 10 or 5.75).")
        return

    if coupon.coupon_type == CouponType.PERCENT:
        if value <= 0 or value > 100:
            await message.answer("Percentage must be greater than 0 and at most 100.")
            return
        coupon.percentage = value.quantize(MONEY_QUANT)
        coupon.amount = None
    else:
        if value <= 0:
            await message.answer("Amount must be greater than zero.")
            return
        coupon.amount = value.quantize(MONEY_QUANT)
        coupon.percentage = None

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state, notice="Coupon value updated.")
    await message.answer("Coupon value updated.")


@router.message(AdminCouponState.edit_min_total)
async def process_edit_min_total_field(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Minimum order update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    if _is_clear(text):
        coupon.min_order_total = None
        notice = "Minimum order requirement cleared."
    else:
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            await message.answer("Enter a valid number (e.g., 20 or 0).")
            return
        if value < 0:
            await message.answer("Minimum order must be zero or greater.")
            return
        coupon.min_order_total = value.quantize(MONEY_QUANT)
        notice = "Minimum order requirement updated."

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


@router.message(AdminCouponState.edit_max_discount)
async def process_edit_max_discount_field(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Maximum discount update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    if _is_clear(text):
        coupon.max_discount_amount = None
        notice = "Maximum discount cleared."
    else:
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            await message.answer("Enter a valid number (e.g., 15 or 7.25).")
            return
        if value <= 0:
            await message.answer("Maximum discount must be greater than zero.")
            return
        coupon.max_discount_amount = value.quantize(MONEY_QUANT)
        notice = "Maximum discount updated."

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


@router.message(AdminCouponState.edit_max_redemptions)
async def process_edit_max_redemptions_field(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Limit update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    if _is_clear(text):
        coupon.max_redemptions = None
        notice = "Total redemption limit cleared."
    else:
        try:
            value = int(text)
        except ValueError:
            await message.answer("Enter a positive integer.")
            return
        if value <= 0:
            await message.answer("Total redemption limit must be greater than zero.")
            return
        coupon.max_redemptions = value
        notice = "Total redemption limit updated."

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


@router.message(AdminCouponState.edit_per_user_limit)
async def process_edit_per_user_limit_field(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Per-user limit update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    if _is_clear(text):
        coupon.per_user_limit = None
        notice = "Per-user limit cleared."
    else:
        try:
            value = int(text)
        except ValueError:
            await message.answer("Enter a positive integer.")
            return
        if value <= 0:
            await message.answer("Per-user limit must be greater than zero.")
            return
        coupon.per_user_limit = value
        notice = "Per-user limit updated."

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


@router.message(AdminCouponState.edit_start_at)
async def process_edit_start_at_field(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "Start date update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    previous = coupon.start_at
    if _is_clear(text):
        coupon.start_at = None
    else:
        try:
            coupon.start_at = _parse_datetime_input(text)
        except ValueError:
            await message.answer("Enter a valid date/time (e.g., 2025-03-01 or 2025-03-01 12:30).")
            return

    try:
        _validate_date_range(coupon)
    except ValueError as exc:
        coupon.start_at = previous
        await message.answer(str(exc))
        return

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    notice = "Start date updated." if coupon.start_at else "Start date cleared."
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


@router.message(AdminCouponState.edit_end_at)
async def process_edit_end_at_field(message: Message, session: AsyncSession, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _is_cancel(text):
        await _cancel_edit(message, session, state, "End date update cancelled.")
        return

    coupon = await _load_coupon_for_edit(session, state)
    if coupon is None:
        await _cancel_edit(message, session, state, "Coupon context lost. Please open the coupon again.")
        return

    previous = coupon.end_at
    if _is_clear(text):
        coupon.end_at = None
    else:
        try:
            coupon.end_at = _parse_datetime_input(text)
        except ValueError:
            await message.answer("Enter a valid date/time (e.g., 2025-03-31 or 2025-03-31 18:00).")
            return

    try:
        _validate_date_range(coupon)
    except ValueError as exc:
        coupon.end_at = previous
        await message.answer(str(exc))
        return

    await session.flush()
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    notice = "End date updated." if coupon.end_at else "End date cleared."
    await _render_coupon_detail_from_context(message.bot, session, state, notice=notice)
    await message.answer(notice)


def _coupon_type_keyboard() -> InlineKeyboardMarkup:
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    for key, label in COUPON_TYPE_LABELS.items():
        builder.button(
            text=label,
            callback_data=f"admin:coupon:type:{key.value}",
        )
    builder.adjust(1)
    return builder.as_markup()


async def _render_coupons_overview(message: Message, session: AsyncSession, *, notice: str | None = None) -> None:
    repo = CouponRepository(session)
    coupons = await repo.list_recent(limit=10)
    total_active = sum(1 for c in coupons if c.status == CouponStatus.ACTIVE)
    total_inactive = sum(1 for c in coupons if c.status != CouponStatus.ACTIVE)

    lines = [
        "<b>Coupons</b>",
        f"Active: {total_active}",
        f"Inactive/expired: {total_inactive}",
    ]
    if coupons:
        lines.append("")
        lines.append("<b>Recent coupons</b>")
        for coupon in coupons:
            amount = _describe_coupon_value(coupon)
            lines.append(f"{coupon.code} · {coupon.status.value} · {amount}")
    else:
        lines.append("")
        lines.append("No coupons have been created yet.")

    text = "\n".join(lines)
    if notice:
        text = f"{notice}\n\n{text}"

    try:
        await message.edit_text(
            text,
            reply_markup=coupon_dashboard_keyboard(coupons),
            disable_web_page_preview=True,
        )
    except Exception:
        await message.answer(
            text,
            reply_markup=coupon_dashboard_keyboard(coupons),
            disable_web_page_preview=True,
        )


def _describe_coupon_value(coupon: Coupon) -> str:
    if coupon.coupon_type == CouponType.PERCENT:
        percentage = coupon.percentage or Decimal("0")
        return f"{percentage}%"
    amount = coupon.amount or Decimal("0")
    return f"{amount}"


async def _render_coupon_detail(
    message: Message,
    session: AsyncSession,
    coupon_id: int,
    *,
    state: FSMContext | None = None,
    notice: str | None = None,
) -> bool:
    return await _render_coupon_detail_to_ids(
        message.bot,
        session,
        coupon_id,
        message.chat.id,
        message.message_id,
        state=state,
        notice=notice,
    )


async def _render_coupon_detail_to_ids(
    bot,
    session: AsyncSession,
    coupon_id: int,
    chat_id: int,
    message_id: int,
    *,
    state: FSMContext | None = None,
    notice: str | None = None,
) -> bool:
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        return False

    text = await _format_coupon_details(session, coupon)
    if notice:
        text = f"{notice}\n\n{text}"

    try:
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=coupon_details_keyboard(coupon),
            disable_web_page_preview=True,
        )
        if state is not None:
            await _store_detail_context_by_ids(state, chat_id, message_id, coupon.id)
    except TelegramBadRequest:
        sent = await bot.send_message(
            chat_id,
            text,
            reply_markup=coupon_details_keyboard(coupon),
            disable_web_page_preview=True,
        )
        if state is not None:
            await _store_detail_context(state, sent, coupon.id)
    return True


async def _format_coupon_details(session: AsyncSession, coupon: Coupon) -> str:
    usage = await CouponService(session).usage_summary(coupon, recent_limit=0)
    total_used = int(usage.get("total", 0))
    unique_users = int(usage.get("unique_users", 0))
    lines = [
        "<b>Coupon details</b>",
        f"Code: <code>{coupon.code}</code>",
        f"Name: {coupon.name or '-'}",
        f"Description: {coupon.description or '-'}",
        f"Status: {coupon.status.value.replace('_', ' ').title()}",
        f"Type: {COUPON_TYPE_LABELS.get(coupon.coupon_type, coupon.coupon_type.value)}",
        f"Value: {_describe_coupon_value(coupon)}",
        f"Auto-apply: {'ON' if coupon.auto_apply else 'OFF'}",
        f"Minimum order: {coupon.min_order_total or '-'}",
        f"Maximum discount: {coupon.max_discount_amount or '-'}",
    ]
    if coupon.max_redemptions is not None:
        remaining = max(coupon.max_redemptions - total_used, 0)
        lines.append(f"Total redemption limit: {coupon.max_redemptions} (used {total_used}, remaining {remaining})")
    else:
        lines.append(f"Total redemptions recorded: {total_used}")
    lines.append(f"Per-user limit: {coupon.per_user_limit or '-'}")
    lines.append(f"Unique customers: {unique_users}")
    lines.append(f"Starts: {_format_dt(coupon.start_at)}")
    lines.append(f"Ends: {_format_dt(coupon.end_at)}")
    lines.append("")
    lines.append("Use the buttons below to manage this coupon.")
    return "\n".join(lines)


def _format_coupon_usage(coupon: Coupon, usage: dict[str, object]) -> str:
    total_used = int(usage.get("total", 0))
    unique_users = int(usage.get("unique_users", 0))
    recent = list(usage.get("recent") or [])

    lines = [
        f"<b>Usage for {coupon.code}</b>",
        f"Total redemptions: {total_used}",
        f"Unique customers: {unique_users}",
    ]
    if coupon.max_redemptions is not None:
        remaining = max(coupon.max_redemptions - total_used, 0)
        lines.append(f"Limit: {coupon.max_redemptions} (remaining {remaining})")
    if coupon.per_user_limit is not None:
        lines.append(f"Per-user limit: {coupon.per_user_limit}")

    if recent:
        lines.append("")
        lines.append("<b>Recent redemptions</b>")
        for redemption in recent:
            lines.append(_format_redemption_line(redemption))
    else:
        lines.append("")
        lines.append("No redemptions recorded yet.")

    return "\n".join(lines)


def _format_redemption_line(redemption) -> str:
    timestamp = _format_dt(getattr(redemption, "created_at", None))
    amount = getattr(redemption, "amount_applied", Decimal("0"))
    try:
        amount_text = str(amount)
    except Exception:  # noqa: BLE001
        amount_text = "-"

    user = getattr(redemption, "user", None)
    if user and getattr(user, "telegram_id", None):
        user_label = f"user {user.telegram_id}"
        if getattr(user, "username", None):
            user_label = f"{user_label} (@{user.username})"
    else:
        user_label = f"profile #{getattr(redemption, 'user_id', '?')}"

    order = getattr(redemption, "order", None)
    if order and getattr(order, "public_id", None):
        order_label = order.public_id
    else:
        order_id = getattr(redemption, "order_id", None)
        order_label = f"order #{order_id}" if order_id else "no order"

    return f"{timestamp} · {amount_text} · {user_label} · {order_label}"


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def _store_detail_context(state: FSMContext | None, message: Message, coupon_id: int) -> None:
    if state is None:
        return
    await state.update_data(
        coupon_detail_chat=message.chat.id,
        coupon_detail_message=message.message_id,
        coupon_detail_coupon_id=coupon_id,
    )


async def _store_detail_context_by_ids(
    state: FSMContext | None,
    chat_id: int,
    message_id: int,
    coupon_id: int,
) -> None:
    if state is None:
        return
    await state.update_data(
        coupon_detail_chat=chat_id,
        coupon_detail_message=message_id,
        coupon_detail_coupon_id=coupon_id,
    )


async def _render_coupon_detail_from_context(bot, session: AsyncSession, state: FSMContext, *, notice: str | None = None) -> None:
    data = await state.get_data()
    chat_id = data.get("coupon_detail_chat")
    message_id = data.get("coupon_detail_message")
    coupon_id = data.get("coupon_detail_coupon_id")
    if not all([chat_id, message_id, coupon_id]):
        return
    await _render_coupon_detail_to_ids(
        bot,
        session,
        int(coupon_id),
        int(chat_id),
        int(message_id),
        state=state,
        notice=notice,
    )


async def _load_coupon_for_edit(session: AsyncSession, state: FSMContext) -> Coupon | None:
    data = await state.get_data()
    coupon_id = data.get("edit_coupon_id")
    if not coupon_id:
        return None
    repo = CouponRepository(session)
    return await repo.get_by_id(int(coupon_id))


async def _cancel_edit(message: Message, session: AsyncSession, state: FSMContext, notice: str) -> None:
    await state.set_state(None)
    await state.update_data(edit_coupon_id=None)
    await _render_coupon_detail_from_context(message.bot, session, state)
    await message.answer(notice)


def _extract_coupon_id(payload: str, prefix: str) -> int | None:
    raw = payload.removeprefix(prefix)
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_datetime_input(text: str) -> datetime:
    cleaned = text.strip()
    try:
        value = datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                value = datetime.strptime(cleaned, fmt)
                if fmt == "%Y-%m-%d":
                    value = value.replace(hour=0, minute=0, second=0)
                break
            except ValueError:
                continue
        else:
            raise ValueError from None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value


def _validate_date_range(coupon: Coupon) -> None:
    if coupon.start_at and coupon.end_at and coupon.start_at > coupon.end_at:
        raise ValueError("Start date must be before end date.")


def _is_cancel(text: str) -> bool:
    return text.lower() in {"/cancel", "cancel"}


def _is_clear(text: str) -> bool:
    return text.lower() in {"/clear", "clear"}
