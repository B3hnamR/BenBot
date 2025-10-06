
from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.keyboards.orders import (
    ORDER_CANCEL_ORDER_PREFIX,
    ORDER_LIST_BACK_CALLBACK,
    ORDER_VIEW_PREFIX,
    order_details_keyboard,
    orders_list_keyboard,
)
from app.bot.keyboards.subscription import (
    SUBSCRIPTION_REFRESH_CALLBACK,
    build_subscription_keyboard,
)
from app.core.config import get_settings
from app.core.enums import OrderStatus
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories import RequiredChannelRepository, UserRepository
from app.services.container import membership_service
from app.services.order_service import OrderService

router = Router(name="common")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(
        "Welcome to Ben Bot!\nUse the interactive menu below to browse products, manage orders, or contact support.",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(message.from_user.id)),
    )


@router.callback_query(F.data == MainMenuCallback.ACCOUNT.value)
async def handle_account(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_orders_overview(callback, session)
    await callback.answer()


@router.callback_query(F.data == ORDER_LIST_BACK_CALLBACK)
async def handle_orders_back(callback: CallbackQuery, session: AsyncSession) -> None:
    await _render_orders_overview(callback, session)
    await callback.answer()


@router.callback_query(F.data.startswith(ORDER_VIEW_PREFIX))
async def handle_order_view(callback: CallbackQuery, session: AsyncSession) -> None:
    public_id = callback.data.removeprefix(ORDER_VIEW_PREFIX)
    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await callback.answer("User profile not found.", show_alert=True)
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None or order.user_id != profile.id:
        await callback.answer("Order not found.", show_alert=True)
        return

    await order_service.enforce_expiration(order)

    await _safe_edit_message(
        callback.message,
        _format_order_details(order),
        reply_markup=order_details_keyboard(order),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ORDER_CANCEL_ORDER_PREFIX))
async def handle_order_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    public_id = callback.data.removeprefix(ORDER_CANCEL_ORDER_PREFIX)
    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await callback.answer("User profile not found.", show_alert=True)
        return

    order_service = OrderService(session)
    order = await order_service.get_order_by_public_id(public_id)
    if order is None or order.user_id != profile.id:
        await callback.answer("Order not found.", show_alert=True)
        return

    if order.status != OrderStatus.AWAITING_PAYMENT:
        await callback.answer("Order cannot be cancelled.", show_alert=True)
        return

    await order_service.mark_cancelled(order)
    await _render_orders_overview(callback, session)
    await callback.answer("Order cancelled")


@router.callback_query(F.data == MainMenuCallback.SUPPORT.value)
async def handle_support(callback: CallbackQuery) -> None:
    await _safe_edit_message(
        callback.message,
        "Support center is under construction. Use this menu later to raise tickets or chat with the team.",
        reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == SUBSCRIPTION_REFRESH_CALLBACK)
async def handle_subscription_refresh(callback: CallbackQuery, session: AsyncSession) -> None:
    channel_repo = RequiredChannelRepository(session)
    channels = await channel_repo.list_active()

    is_allowed = await membership_service.user_can_access(
        bot=callback.bot,
        user_id=callback.from_user.id,
        session=session,
        channels=channels,
    )

    if is_allowed:
        membership_service.invalidate_user(callback.from_user.id)
        await callback.answer("Thanks! Access granted.")
        await _safe_edit_message(
            callback.message,
            "Welcome back! Choose an option below.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    keyboard = build_subscription_keyboard(list(channels)) if channels else None
    await callback.answer("You still need to join the required channels.", show_alert=True)
    await _safe_edit_message(
        callback.message,
        "Please join the required channel(s) before continuing.\nTap 'I've Joined' once you have access.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "subscription:no_link")
async def handle_subscription_no_link(callback: CallbackQuery) -> None:
    await callback.answer(
        "Channel link is not configured. Please contact the administrator.",
        show_alert=True,
    )


async def _render_orders_overview(callback: CallbackQuery, session: AsyncSession) -> None:
    user_repo = UserRepository(session)
    profile = await user_repo.get_by_telegram_id(callback.from_user.id)
    if profile is None:
        await _safe_edit_message(
            callback.message,
            "We could not locate your profile. Try again later.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    order_service = OrderService(session)
    orders = await order_service.list_user_orders(profile.id)

    if not orders:
        await _safe_edit_message(
            callback.message,
            "You have no orders yet.",
            reply_markup=main_menu_keyboard(show_admin=_user_is_owner(callback.from_user.id)),
        )
        return

    summary = _format_orders_overview(orders)
    reply_markup = orders_list_keyboard(orders[:10])
    await _safe_edit_message(callback.message, summary, reply_markup=reply_markup)



def _format_orders_overview(orders: list[Order]) -> str:
    lines = ["<b>Your orders</b>"]
    for order in orders[:10]:
        status = order.status.value.replace("_", " ").title()
        created = order.created_at.strftime("%Y-%m-%d %H:%M") if order.created_at else "-"
        lines.append(f"{status} · {order.total_amount} {order.currency} · created {created}")
    if len(orders) > 10:
        lines.append("…")
    lines.append("")
    lines.append("Select an order to view details.")
    return "
".join(lines)


def _format_order_details(order: Order) -> str:
    lines = [
        f"<b>Order {order.public_id}</b>",
        f"Status: {order.status.value.replace('_', ' ').title()}",
        f"Total: {order.total_amount} {order.currency}",
    ]
    if order.payment_expires_at:
        remaining = order.payment_expires_at - datetime.now(tz=timezone.utc)
        minutes = int(max(0, remaining.total_seconds()) // 60)
        lines.append(f"Payment deadline: {order.payment_expires_at:%Y-%m-%d %H:%M UTC}")
        if minutes > 0:
            lines.append(f"Time remaining: ~{minutes} minutes")
    if order.answers:
        lines.append("")
        lines.append("<b>Details</b>")
        for answer in order.answers:
            lines.append(f"{answer.question_key}: {answer.answer_text or '-'}")
    return "
".join(lines)


async def _safe_edit_message(message, text: str, *, reply_markup=None) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        await message.answer(text, reply_markup=reply_markup)


def _user_is_owner(user_id: int | None) -> bool:
    if user_id is None:
        return False
    settings = get_settings()
    return user_id in settings.owner_user_ids
