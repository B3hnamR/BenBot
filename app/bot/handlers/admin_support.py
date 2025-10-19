from __future__ import annotations

from typing import Literal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.admin import _extract_oxapay_meta
from app.bot.keyboards.admin import AdminMenuCallback
from app.bot.keyboards.admin_support import (
    ADMIN_SUPPORT_ASSIGN_PREFIX,
    ADMIN_SUPPORT_LIST_PREFIX,
    ADMIN_SUPPORT_MENU_ALL,
    ADMIN_SUPPORT_MENU_ASSIGNED,
    ADMIN_SUPPORT_MENU_AWAITING_USER,
    ADMIN_SUPPORT_MENU_OPEN,
    ADMIN_SUPPORT_PRIORITY_PREFIX,
    ADMIN_SUPPORT_REPLY_PREFIX,
    ADMIN_SUPPORT_STATUS_PREFIX,
    ADMIN_SUPPORT_VIEW_PREFIX,
    admin_support_list_keyboard,
    admin_support_menu_keyboard,
    admin_support_ticket_keyboard,
)
from app.bot.states.admin_support import AdminSupportState
from app.core.enums import SupportTicketPriority, SupportTicketStatus
from app.services.support_service import SupportService, TicketFilters

router = Router(name="admin_support")

ADMIN_SUPPORT_PAGE_SIZE = 10


@router.callback_query(F.data == AdminMenuCallback.MANAGE_SUPPORT.value)
async def handle_admin_support_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    service = SupportService(session)
    status_counts = await service.status_counts()
    priority_counts = await service.priority_counts()
    text = _format_support_overview(status_counts, priority_counts)
    markup = admin_support_menu_keyboard()
    await _safe_edit_message(callback.message, text, markup)
    await callback.answer()


@router.callback_query(F.data.in_({ADMIN_SUPPORT_MENU_OPEN, ADMIN_SUPPORT_MENU_ALL, ADMIN_SUPPORT_MENU_ASSIGNED, ADMIN_SUPPORT_MENU_AWAITING_USER}))
async def handle_admin_support_menu_filter(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    filter_code = _menu_filter_code(callback.data)
    await _render_support_ticket_list(callback, session, state, filter_code=filter_code, page=0)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_LIST_PREFIX))
async def handle_admin_support_list_page(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    remainder = callback.data.removeprefix(ADMIN_SUPPORT_LIST_PREFIX)
    try:
        filter_code, page_val = remainder.split(":")
    except ValueError:
        filter_code, page_val = "open", "0"
    try:
        page = max(0, int(page_val))
    except ValueError:
        page = 0
    await _render_support_ticket_list(callback, session, state, filter_code=filter_code, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_VIEW_PREFIX))
async def handle_admin_support_view_ticket(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(ADMIN_SUPPORT_VIEW_PREFIX)
    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(public_id)
    if ticket is None:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    await state.update_data(active_support_ticket=public_id)
    data = await state.get_data()
    filter_code = data.get("support_filter", "open")
    page = int(data.get("support_page", 0))
    await _safe_edit_message(
        callback.message,
        _format_admin_ticket_detail(ticket),
        admin_support_ticket_keyboard(ticket, admin_id=callback.from_user.id, filter_code=filter_code, page=page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_REPLY_PREFIX))
async def handle_admin_support_reply(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    public_id = callback.data.removeprefix(ADMIN_SUPPORT_REPLY_PREFIX)
    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(public_id)
    if ticket is None:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    await state.set_state(AdminSupportState.replying)
    await state.update_data(active_support_ticket=public_id)
    await callback.message.answer("Send your reply. Use /cancel to abort.")
    await callback.answer()


@router.message(AdminSupportState.replying)
async def handle_admin_support_reply_message(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    text = (message.text or "").strip()
    if text.lower() in {"/cancel", "cancel"}:
        await state.set_state(None)
        await state.update_data(active_support_ticket=None)
        await message.answer("Reply cancelled.")
        return
    if not text:
        await message.answer("Reply cannot be empty. Send the message or /cancel.")
        return

    data = await state.get_data()
    public_id = data.get("active_support_ticket")
    filter_code = data.get("support_filter", "open")
    page = int(data.get("support_page", 0))
    if not public_id:
        await state.set_state(None)
        await message.answer("Ticket session expired.")
        return

    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(public_id)
    if ticket is None:
        await state.set_state(None)
        await message.answer("Ticket no longer exists.")
        return

    await service.add_admin_message(
        ticket,
        body=text,
        admin_telegram_id=message.from_user.id,
    )

    user_chat_id = getattr(getattr(ticket, "user", None), "telegram_id", None)
    if user_chat_id:
        try:
            await message.bot.send_message(
                user_chat_id,
                _format_user_notification(ticket, text),
                disable_web_page_preview=True,
            )
        except Exception:
            pass

    await state.set_state(None)
    await state.update_data(
        support_filter=filter_code,
        support_page=page,
        active_support_ticket=None,
    )
    await message.answer(
        _format_admin_ticket_detail(ticket),
        reply_markup=admin_support_ticket_keyboard(
            ticket,
            admin_id=message.from_user.id,
            filter_code=filter_code,
            page=page,
        ),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_STATUS_PREFIX))
async def handle_admin_support_status(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    remainder = callback.data.removeprefix(ADMIN_SUPPORT_STATUS_PREFIX)
    ticket_id, status_value = remainder.split(":")
    try:
        status = SupportTicketStatus(status_value)
    except ValueError:
        await callback.answer("Invalid status.", show_alert=True)
        return
    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(ticket_id)
    if ticket is None:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    await service.set_status(ticket, status)
    data = await state.get_data()
    filter_code = data.get("support_filter", "open")
    page = int(data.get("support_page", 0))
    await _safe_edit_message(
        callback.message,
        _format_admin_ticket_detail(ticket),
        admin_support_ticket_keyboard(ticket, admin_id=callback.from_user.id, filter_code=filter_code, page=page),
    )
    await callback.answer("Status updated.")


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_ASSIGN_PREFIX))
async def handle_admin_support_assign(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    remainder = callback.data.removeprefix(ADMIN_SUPPORT_ASSIGN_PREFIX)
    ticket_id, target = remainder.split(":")
    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(ticket_id)
    if ticket is None:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    if target == "me":
        await service.assign_admin(ticket, callback.from_user.id)
    else:
        await service.assign_admin(ticket, None)
    data = await state.get_data()
    filter_code = data.get("support_filter", "open")
    page = int(data.get("support_page", 0))
    await _safe_edit_message(
        callback.message,
        _format_admin_ticket_detail(ticket),
        admin_support_ticket_keyboard(ticket, admin_id=callback.from_user.id, filter_code=filter_code, page=page),
    )
    await callback.answer("Assignment updated.")


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_PRIORITY_PREFIX))
async def handle_admin_support_priority(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    remainder = callback.data.removeprefix(ADMIN_SUPPORT_PRIORITY_PREFIX)
    ticket_id, priority_val = remainder.split(":")
    try:
        priority = SupportTicketPriority(priority_val)
    except ValueError:
        await callback.answer("Invalid priority.", show_alert=True)
        return
    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(ticket_id)
    if ticket is None:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    await service.set_priority(ticket, priority)
    data = await state.get_data()
    filter_code = data.get("support_filter", "open")
    page = int(data.get("support_page", 0))
    await _safe_edit_message(
        callback.message,
        _format_admin_ticket_detail(ticket),
        admin_support_ticket_keyboard(ticket, admin_id=callback.from_user.id, filter_code=filter_code, page=page),
    )
    await callback.answer("Priority updated.")


# Helpers


async def _render_support_ticket_list(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    *,
    filter_code: str,
    page: int,
) -> None:
    service = SupportService(session)
    filters = _filters_for(filter_code, callback.from_user.id)
    tickets, has_more = await service.paginate_admin_tickets(page=page, page_size=ADMIN_SUPPORT_PAGE_SIZE, filters=filters)
    has_prev = page > 0

    await state.update_data(support_filter=filter_code, support_page=page)

    if not tickets and page > 0:
        await _render_support_ticket_list(callback, session, state, filter_code=filter_code, page=max(page - 1, 0))
        return

    text = _format_support_list(tickets, filter_code=filter_code, page=page, has_prev=has_prev, has_next=has_more)
    markup = admin_support_list_keyboard(
        tickets,
        filter_code=filter_code,
        page=page,
        has_prev=has_prev,
        has_next=has_more,
    )
    await _safe_edit_message(callback.message, text, markup)


def _filters_for(filter_code: str, admin_id: int | None) -> TicketFilters:
    if filter_code == "mine":
        return TicketFilters(assigned_admin_id=admin_id)
    if filter_code == "await_user":
        return TicketFilters(statuses={SupportTicketStatus.AWAITING_USER})
    if filter_code == "await_admin":
        return TicketFilters(statuses={SupportTicketStatus.AWAITING_ADMIN})
    if filter_code == "all":
        return TicketFilters()
    return TicketFilters(only_open=True)


def _menu_filter_code(callback_data: str) -> str:
    mapping = {
        ADMIN_SUPPORT_MENU_OPEN: "open",
        ADMIN_SUPPORT_MENU_ASSIGNED: "mine",
        ADMIN_SUPPORT_MENU_AWAITING_USER: "await_user",
        ADMIN_SUPPORT_MENU_ALL: "all",
    }
    return mapping.get(callback_data, "open")


def _format_support_overview(
    status_counts: dict[SupportTicketStatus, int],
    priority_counts: dict[SupportTicketPriority, int],
) -> str:
    lines = ["<b>Support dashboard</b>"]
    total = sum(status_counts.values())
    lines.append(f"Total tickets: {total}")
    lines.append("")
    lines.append("<b>By status</b>")
    for status in SupportTicketStatus:
        lines.append(f"{status.value.replace('_', ' ').title()}: {status_counts.get(status, 0)}")
    lines.append("")
    lines.append("<b>By priority</b>")
    for priority in SupportTicketPriority:
        lines.append(f"{priority.value.title()}: {priority_counts.get(priority, 0)}")
    lines.append("")
    lines.append("Use the buttons below to review ticket queues.")
    return "\n".join(lines)


def _format_support_list(
    tickets: list[SupportTicket],
    *,
    filter_code: str,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> str:
    lines = ["<b>Support tickets</b>"]
    label = filter_code.replace("_", " ").title()
    hints = []
    if has_prev:
        hints.append("Prev available")
    if has_next:
        hints.append("Next available")
    info = f"{label} • page {page + 1}"
    if hints:
        info += f" ({', '.join(hints)})"
    lines.append(info)
    if not tickets:
        lines.append("")
        lines.append("No tickets in this view.")
        return "\n".join(lines)
    base_index = page * ADMIN_SUPPORT_PAGE_SIZE
    for idx, ticket in enumerate(tickets, start=base_index + 1):
        status = ticket.status.value.replace("_", " ").title()
        priority = ticket.priority.value.title()
        subject = ticket.subject
        user = getattr(getattr(ticket, "user", None), "telegram_id", ticket.user_id)
        lines.append(f"{idx}. {status} • {priority} • {subject} (user {user})")
    return "\n".join(lines)


def _format_admin_ticket_detail(ticket: SupportTicket) -> str:
    status = ticket.status.value.replace("_", " ").title()
    priority = ticket.priority.value.title()
    user = getattr(getattr(ticket, "user", None), "telegram_id", ticket.user_id)
    lines = [
        f"<b>Ticket {ticket.public_id}</b>",
        f"Subject: {ticket.subject}",
        f"Status: {status}",
        f"Priority: {priority}",
        f"User: {user}",
    ]
    if ticket.category:
        lines.append(f"Category: {ticket.category}")
    if ticket.assigned_admin_id:
        lines.append(f"Assigned admin: {ticket.assigned_admin_id}")
    if ticket.order is not None:
        product_name = getattr(ticket.order.product, "name", "-")
        lines.append(f"Order: {ticket.order.public_id} • {product_name}")
        oxapay = _extract_oxapay_meta(ticket.order)
        if oxapay.get("status"):
            lines.append(f"Payment status: {oxapay.get('status')}")
    if ticket.meta:
        tags = ticket.meta.get("tags") if isinstance(ticket.meta, dict) else None
        if tags:
            lines.append(f"Tags: {', '.join(tags)}")
    if ticket.last_activity_at:
        lines.append(f"Last activity: {ticket.last_activity_at:%Y-%m-%d %H:%M UTC}")
    lines.append("")
    lines.append("<b>Conversation</b>")
    history = ticket.messages[-15 :]
    if not history:
        lines.append("No messages yet.")
    else:
        for message in history:
            role = message.author_role.value.title()
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M UTC") if message.created_at else "-"
            author = message.author_id if message.author_id is not None else "-"
            lines.append(f"{role} • {timestamp} • id {author}")
            lines.append(message.body)
            lines.append("")
    return "\n".join(lines).rstrip()


def _format_user_notification(ticket: SupportTicket, body: str) -> str:
    lines = [
        "<b>Support update</b>",
        f"Ticket: <code>{ticket.public_id}</code>",
        "",
        body,
    ]
    return "\n".join(lines)


async def _safe_edit_message(message, text: str, reply_markup) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception:
        await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
