from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Sequence

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.admin import (
    ADMIN_COUPON_TOGGLE_PREFIX,
    ADMIN_COUPON_VIEW_PREFIX,
    AdminCouponCallback,
    AdminMenuCallback,
    coupon_dashboard_keyboard,
    coupon_details_keyboard,
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
async def handle_coupon_view(callback: CallbackQuery, session: AsyncSession) -> None:
    raw = callback.data.removeprefix(ADMIN_COUPON_VIEW_PREFIX)
    try:
        coupon_id = int(raw)
    except ValueError:
        await callback.answer("Invalid coupon ID.", show_alert=True)
        return
    repo = CouponRepository(session)
    coupon = await repo.get_by_id(coupon_id)
    if coupon is None:
        await callback.answer("Coupon not found.", show_alert=True)
        return
    text = _format_coupon_details(coupon)
    await callback.message.edit_text(
        text,
        reply_markup=coupon_details_keyboard(coupon),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_COUPON_TOGGLE_PREFIX))
async def handle_coupon_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    raw = callback.data.removeprefix(ADMIN_COUPON_TOGGLE_PREFIX)
    try:
        coupon_id = int(raw)
    except ValueError:
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

    await callback.answer(notice)
    text = _format_coupon_details(coupon)
    await callback.message.edit_text(
        text,
        reply_markup=coupon_details_keyboard(coupon),
        disable_web_page_preview=True,
    )


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


def _format_coupon_details(coupon: Coupon) -> str:
    lines = [
        "<b>Coupon details</b>",
        f"Code: <code>{coupon.code}</code>",
        f"Name: {coupon.name or '-'}",
        f"Status: {coupon.status.value.replace('_', ' ').title()}",
        f"Type: {COUPON_TYPE_LABELS.get(coupon.coupon_type, coupon.coupon_type.value)}",
        f"Value: {_describe_coupon_value(coupon)}",
    ]
    if coupon.min_order_total:
        lines.append(f"Minimum order: {coupon.min_order_total}")
    if coupon.max_redemptions:
        lines.append(f"Total redemption limit: {coupon.max_redemptions}")
    if coupon.per_user_limit:
        lines.append(f"Per-user limit: {coupon.per_user_limit}")
    if coupon.start_at:
        lines.append(f"Starts: {_format_dt(coupon.start_at)}")
    if coupon.end_at:
        lines.append(f"Ends: {_format_dt(coupon.end_at)}")
    total_redemptions = len(coupon.redemptions or [])
    lines.append(f"Recorded redemptions: {total_redemptions}")
    return "\n".join(lines)


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _is_cancel(text: str) -> bool:
    return text.lower() in {"/cancel", "cancel"}
