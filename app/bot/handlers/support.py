from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.bot.keyboards.main_menu import MainMenuCallback, main_menu_keyboard
from app.bot.keyboards.admin_support import ADMIN_SUPPORT_VIEW_PREFIX
from app.bot.keyboards.support import (
    SUPPORT_BACK_MAIN,
    SUPPORT_CANCEL,
    SUPPORT_CATEGORY_PREFIX,
    SUPPORT_MY_TICKETS,
    SUPPORT_NEW_TICKET,
    SUPPORT_ORDER_CREATE_PREFIX,
    SUPPORT_ORDER_PAGE_PREFIX,
    SUPPORT_ORDER_SELECT_PREFIX,
    SUPPORT_TICKET_LIST_PAGE_PREFIX,
    SUPPORT_TICKET_REPLY_PREFIX,
    SUPPORT_TICKET_RESOLVE_PREFIX,
    SUPPORT_TICKET_REOPEN_PREFIX,
    SUPPORT_TICKET_VIEW_PREFIX,
    support_categories_keyboard,
    support_main_keyboard,
    support_orders_keyboard,
    support_ticket_detail_keyboard,
    support_ticket_list_keyboard,
)
from app.bot.states.support import SupportState
from app.core.enums import SupportTicketPriority, SupportTicketStatus
from app.infrastructure.db.repositories import OrderRepository, UserRepository
from app.infrastructure.db.models import SupportTicket
from app.services.order_service import OrderService
from app.services.support_service import SupportService

router = Router(name="support")

SUPPORT_USER_PAGE_SIZE = 5
SUPPORT_ORDER_PAGE_SIZE = 5
SUPPORT_MESSAGE_HISTORY_LIMIT = 10

DEFAULT_SUPPORT_CATEGORIES = ["General inquiry", "Billing issue", "Technical problem", "Order delivery"]


@router.callback_query(F.data == MainMenuCallback.SUPPORT.value)
async def handle_support_entry(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    profile = await _ensure_profile(session, callback.from_user.id)
    service = SupportService(session)
    tickets, _ = await service.paginate_user_tickets(profile.id, page=0, page_size=1)
    await state.set_state(SupportState.menu)
    await state.update_data(
        support_ticket_page=0,
        support_order_page=0,
    )
    text = _support_intro_text()
    markup = support_main_keyboard(has_tickets=bool(tickets))
    await _safe_edit_message(callback.message, text, markup)
    await callback.answer()


@router.callback_query(F.data == SUPPORT_BACK_MAIN)
async def handle_support_back_main(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _safe_edit_message(
        callback.message,
        "Main menu",
        main_menu_keyboard(show_admin=_is_owner(callback.from_user.id)),
    )
    await callback.answer()


@router.callback_query(F.data == SUPPORT_CANCEL)
async def handle_support_cancel(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await handle_support_entry(callback, session, state)


@router.callback_query(F.data == SUPPORT_NEW_TICKET)
async def handle_support_new_ticket(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await _start_ticket_creation(callback, session, state, order_public_id=None)


@router.callback_query(F.data.startswith(SUPPORT_ORDER_CREATE_PREFIX))
async def handle_support_new_ticket_for_order(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(SUPPORT_ORDER_CREATE_PREFIX)
    await _start_ticket_creation(callback, session, state, order_public_id=public_id or None)


@router.callback_query(F.data.startswith(SUPPORT_CATEGORY_PREFIX))
async def handle_support_category(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    category = callback.data.removeprefix(SUPPORT_CATEGORY_PREFIX)
    if category == "-":
        category = None
    await state.update_data(support_category=category)
    await callback.answer()
    await _prompt_order_selection(callback, session, state, reset_page=True)


@router.callback_query(F.data.startswith(SUPPORT_ORDER_PAGE_PREFIX))
async def handle_support_order_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    raw = callback.data.removeprefix(SUPPORT_ORDER_PAGE_PREFIX)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    await state.update_data(support_order_page=page)
    await callback.answer()
    await _prompt_order_selection(callback, session, state, reset_page=False)


@router.callback_query(F.data.startswith(SUPPORT_ORDER_SELECT_PREFIX))
async def handle_support_order_select(callback: CallbackQuery, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(SUPPORT_ORDER_SELECT_PREFIX)
    if public_id == "-":
        public_id = None
    await state.update_data(support_order_public_id=public_id)
    await state.set_state(SupportState.entering_subject)
    await callback.message.answer("Please enter a short subject for your request (max 160 characters).")
    await callback.answer()


@router.message(SupportState.entering_subject)
async def handle_support_subject(message: Message, state: FSMContext) -> None:
    subject = (message.text or "").strip()
    if not subject:
        await message.answer("Subject cannot be empty. Please send a short description.")
        return
    await state.update_data(support_subject=subject[:160])
    await state.set_state(SupportState.entering_message)
    await message.answer("Describe your issue with as much detail as possible. You can send text only for now.")


@router.message(SupportState.entering_message)
async def handle_support_message(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    body = (message.text or "").strip()
    if not body:
        await message.answer("Message cannot be empty. Please describe your issue.")
        return

    profile = await _ensure_profile(session, message.from_user.id)
    data = await state.get_data()
    subject = data.get("support_subject")
    if not subject:
        await message.answer("Something went wrong, please start again.")
        await state.clear()
        return

    order_public_id = data.get("support_order_public_id")
    order_id = None
    order = None
    if order_public_id:
        order_service = OrderService(session)
        order = await order_service.get_order_by_public_id(order_public_id)
        if order is not None and order.user_id == profile.id:
            order_id = order.id

    category = data.get("support_category")
    service = SupportService(session)
    ticket = await service.create_ticket(
        user_id=profile.id,
        subject=subject,
        body=body,
        category=category,
        priority=SupportTicketPriority.NORMAL,
        order_id=order_id,
        author_telegram_id=message.from_user.id,
    )
    ticket.user = profile
    if order_id and order is not None:
        ticket.order = order
    await service.ensure_user_loaded(ticket)
    await service.ensure_order_loaded(ticket)

    await state.set_state(SupportState.menu)
    await state.update_data(support_ticket_page=0)
    await message.answer(
        _format_ticket_detail(ticket),
        reply_markup=support_ticket_detail_keyboard(ticket),
        disable_web_page_preview=True,
    )
    await _notify_admins_new_ticket(message.bot, ticket)


@router.callback_query(F.data == SUPPORT_MY_TICKETS)
async def handle_support_ticket_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await _render_ticket_list(callback, session, state, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith(SUPPORT_TICKET_LIST_PAGE_PREFIX))
async def handle_support_ticket_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    raw = callback.data.removeprefix(SUPPORT_TICKET_LIST_PAGE_PREFIX)
    try:
        page = max(0, int(raw))
    except ValueError:
        page = 0
    await _render_ticket_list(callback, session, state, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith(SUPPORT_TICKET_VIEW_PREFIX))
async def handle_support_ticket_view(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(SUPPORT_TICKET_VIEW_PREFIX)
    ticket = await SupportService(session).get_ticket_by_public_id(public_id)
    profile = await _ensure_profile(session, callback.from_user.id)
    if ticket is None or ticket.user_id != profile.id:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    await state.set_state(SupportState.menu)
    await _safe_edit_message(
        callback.message,
        _format_ticket_detail(ticket),
        support_ticket_detail_keyboard(ticket),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(SUPPORT_TICKET_REPLY_PREFIX))
async def handle_support_ticket_reply(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(SUPPORT_TICKET_REPLY_PREFIX)
    ticket = await SupportService(session).get_ticket_by_public_id(public_id)
    profile = await _ensure_profile(session, callback.from_user.id)
    if ticket is None or ticket.user_id != profile.id:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    await state.set_state(SupportState.replying)
    await state.update_data(active_ticket=public_id)
    await callback.message.answer("Send your reply. Use /cancel to stop replying.")
    await callback.answer()


@router.message(SupportState.replying)
async def handle_support_ticket_reply_message(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    text = (message.text or "").strip()
    if text.lower() in {"/cancel", "cancel"}:
        await state.set_state(SupportState.menu)
        await message.answer("Reply cancelled.")
        return
    if not text:
        await message.answer("Reply cannot be empty. Please send your message or /cancel.")
        return

    data = await state.get_data()
    public_id = data.get("active_ticket")
    if not public_id:
        await state.set_state(SupportState.menu)
        await message.answer("Ticket session expired. Open the ticket again.")
        return

    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(public_id)
    profile = await _ensure_profile(session, message.from_user.id)
    if ticket is None or ticket.user_id != profile.id:
        await message.answer("Ticket no longer exists.")
        await state.set_state(SupportState.menu)
        return

    await service.add_user_message(
        ticket,
        body=text,
        author_telegram_id=message.from_user.id,
    )
    await service.ensure_user_loaded(ticket)
    await service.ensure_order_loaded(ticket)
    await _notify_admins_ticket_update(message.bot, ticket, text)
    await state.set_state(SupportState.menu)
    await message.answer(
        _format_ticket_detail(ticket),
        reply_markup=support_ticket_detail_keyboard(ticket),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith(SUPPORT_TICKET_RESOLVE_PREFIX))
async def handle_support_ticket_resolve(callback: CallbackQuery, session: AsyncSession) -> None:
    public_id = callback.data.removeprefix(SUPPORT_TICKET_RESOLVE_PREFIX)
    await _update_ticket_status(callback, session, public_id, SupportTicketStatus.RESOLVED)


@router.callback_query(F.data.startswith(SUPPORT_TICKET_REOPEN_PREFIX))
async def handle_support_ticket_reopen(callback: CallbackQuery, session: AsyncSession) -> None:
    public_id = callback.data.removeprefix(SUPPORT_TICKET_REOPEN_PREFIX)
    await _update_ticket_status(callback, session, public_id, SupportTicketStatus.OPEN)


# Helper functions


async def _start_ticket_creation(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    *,
    order_public_id: str | None,
) -> None:
    await state.update_data(
        support_category=None,
        support_subject=None,
        support_order_public_id=order_public_id,
        support_order_page=0,
    )
    await state.set_state(SupportState.choosing_category)
    text = "Choose a category for your request:"
    markup = support_categories_keyboard(DEFAULT_SUPPORT_CATEGORIES)
    await _safe_edit_message(callback.message, text, markup)
    await callback.answer()


async def _prompt_order_selection(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    *,
    reset_page: bool,
) -> None:
    profile = await _ensure_profile(session, callback.from_user.id)
    data = await state.get_data()
    page = 0 if reset_page else int(data.get("support_order_page", 0))
    await state.update_data(support_order_page=page)
    order_service = OrderService(session)
    orders, has_more = await order_service.paginate_user_orders(
        profile.id,
        limit=SUPPORT_ORDER_PAGE_SIZE,
        offset=page * SUPPORT_ORDER_PAGE_SIZE,
    )
    has_prev = page > 0
    text = "Select an order to link with this request (or skip):"
    markup = support_orders_keyboard(
        orders,
        page=page,
        has_prev=has_prev,
        has_next=has_more,
    )
    await _safe_edit_message(callback.message, text, markup)


async def _render_ticket_list(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    *,
    page: int,
) -> None:
    profile = await _ensure_profile(session, callback.from_user.id)
    service = SupportService(session)
    tickets, has_more = await service.paginate_user_tickets(
        profile.id,
        page=page,
        page_size=SUPPORT_USER_PAGE_SIZE,
    )
    has_prev = page > 0
    if not tickets and page > 0:
        await _render_ticket_list(callback, session, state, page=max(page - 1, 0))
        return
    await state.update_data(support_ticket_page=page)
    text = _format_ticket_list(tickets, page=page, page_size=SUPPORT_USER_PAGE_SIZE, has_prev=has_prev, has_next=has_more)
    markup = support_ticket_list_keyboard(
        tickets,
        page=page,
        has_prev=has_prev,
        has_next=has_more,
    )
    await _safe_edit_message(callback.message, text, markup)


async def _update_ticket_status(
    callback: CallbackQuery,
    session: AsyncSession,
    public_id: str,
    status: SupportTicketStatus,
) -> None:
    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(public_id)
    profile = await _ensure_profile(session, callback.from_user.id)
    if ticket is None or ticket.user_id != profile.id:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    await service.set_status(ticket, status)
    await _safe_edit_message(
        callback.message,
        _format_ticket_detail(ticket),
        support_ticket_detail_keyboard(ticket),
    )
    await callback.answer("Status updated.")


def _support_intro_text() -> str:
    lines = [
        "<b>Support center</b>",
        "Create a new ticket for assistance or review existing conversations.",
        "Our team will reach out as soon as possible.",
    ]
    return "\n".join(lines)


def _format_ticket_list(
    tickets: list[SupportTicket],
    *,
    page: int,
    page_size: int,
    has_prev: bool,
    has_next: bool,
) -> str:
    lines = ["<b>My support tickets</b>"]
    page_info = f"Page {page + 1}"
    hints = []
    if has_prev:
        hints.append("Prev available")
    if has_next:
        hints.append("Next available")
    if hints:
        page_info += f" ({', '.join(hints)})"
    lines.append(page_info)
    if not tickets:
        lines.append("You have not created any tickets yet.")
        return "\n".join(lines)
    start_index = page * page_size
    for idx, ticket in enumerate(tickets, start=start_index + 1):
        status = ticket.status.value.replace("_", " ").title()
        lines.append(f"{idx}. {status} - {ticket.subject}")
    lines.append("")
    lines.append("Select a ticket to view conversation or reply.")
    return "\n".join(lines)


def _format_ticket_detail(ticket: SupportTicket) -> str:
    status = ticket.status.value.replace("_", " ").title()
    priority = ticket.priority.value.title()
    last_activity = ticket.last_activity_at.strftime("%Y-%m-%d %H:%M UTC") if ticket.last_activity_at else "-"
    lines = [
        f"<b>Ticket {ticket.public_id}</b>",
        f"Subject: {ticket.subject}",
        f"Status: {status}",
        f"Priority: {priority}",
        f"Last activity: {last_activity}",
    ]
    if ticket.category:
        lines.append(f"Category: {ticket.category}")
    if ticket.order is not None:
        product_name = getattr(ticket.order.product, "name", "-")
        lines.append(f"Order: {ticket.order.public_id} - {product_name}")
    if ticket.assigned_admin_id:
        lines.append(f"Assigned admin: {ticket.assigned_admin_id}")
    if ticket.meta:
        tags = ticket.meta.get("tags")
        if tags:
            lines.append(f"Tags: {', '.join(tags)}")

    lines.append("")
    lines.append("<b>Conversation</b>")
    history = ticket.messages[-SUPPORT_MESSAGE_HISTORY_LIMIT :]
    if not history:
        lines.append("No messages yet.")
    else:
        for message in history:
            author = message.author_role.value.title()
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M UTC") if message.created_at else "-"
            lines.append(f"{author} - {timestamp}")
            lines.append(message.body)
            lines.append("")
    return "\n".join(lines).rstrip()


async def _notify_admins_new_ticket(bot, ticket: SupportTicket) -> None:
    settings = get_settings()
    recipients = set(settings.owner_user_ids or [])
    if not recipients:
        return
    body = ticket.messages[-1].body if ticket.messages else ""
    message = _format_admin_ticket_alert(ticket, body, is_new=True)
    user_id = getattr(getattr(ticket, "user", None), "telegram_id", None)
    for admin_id in recipients:
        if admin_id is None or admin_id == user_id:
            continue
        try:
            await bot.send_message(admin_id, message, disable_web_page_preview=True)
        except Exception:
            continue


async def _notify_admins_ticket_update(bot, ticket: SupportTicket, body: str) -> None:
    settings = get_settings()
    recipients = set(settings.owner_user_ids or [])
    if ticket.assigned_admin_id:
        recipients.add(ticket.assigned_admin_id)
    user_id = getattr(getattr(ticket, "user", None), "telegram_id", None)
    if user_id:
        recipients.discard(user_id)
    if not recipients:
        return
    message = _format_admin_ticket_alert(ticket, body, is_new=False)
    for admin_id in recipients:
        if admin_id is None:
            continue
        try:
            await bot.send_message(admin_id, message, disable_web_page_preview=True)
        except Exception:
            continue


def _format_admin_ticket_alert(ticket: SupportTicket, body: str, *, is_new: bool) -> str:
    prefix = "New support ticket" if is_new else "Customer reply"
    user = getattr(getattr(ticket, "user", None), "telegram_id", ticket.user_id)
    lines = [
        f"<b>{prefix}</b>",
        f"Ticket: <code>{ticket.public_id}</code>",
        f"User: {user}",
        f"Subject: {ticket.subject}",
        f"Status: {ticket.status.value.replace('_', ' ').title()}",
    ]
    if ticket.order is not None:
        lines.append(f"Order: {ticket.order.public_id}")
    lines.append("")
    lines.append(body or "(no message)")
    return "\n".join(lines)


async def _ensure_profile(session: AsyncSession, telegram_id: int):
    profile = await UserRepository(session).get_by_telegram_id(telegram_id)
    if profile is None:
        raise RuntimeError("User profile is required for support flow.")
    return profile


def _is_owner(telegram_id: int | None) -> bool:
    from app.core.config import get_settings

    if telegram_id is None:
        return False
    settings = get_settings()
    return telegram_id in (settings.owner_user_ids or [])


async def _safe_edit_message(message, text: str, reply_markup) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception:
        await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
