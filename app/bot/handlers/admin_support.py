from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    ADMIN_SUPPORT_SETTINGS,
    ADMIN_SUPPORT_ORDER_ACTION_PREFIX,
    ADMIN_SUPPORT_SPAM_PREFIX,
    ADMIN_SUPPORT_PRIORITY_PREFIX,
    ADMIN_SUPPORT_REPLY_PREFIX,
    ADMIN_SUPPORT_STATUS_PREFIX,
    ADMIN_SUPPORT_VIEW_PREFIX,
    admin_support_antispam_keyboard,
    admin_support_list_keyboard,
    admin_support_menu_keyboard,
    admin_support_ticket_keyboard,
    decode_status_code,
)
from app.bot.keyboards.support import support_ticket_notification_keyboard
from app.bot.states.admin_support import AdminSupportState
from app.core.enums import SupportTicketPriority, SupportTicketStatus
from app.services.config_service import ConfigService
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


@router.callback_query(F.data == ADMIN_SUPPORT_SETTINGS)
async def handle_admin_support_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    config_service = ConfigService(session)
    antispam = await config_service.get_support_antispam_settings()
    await _safe_edit_message(
        callback.message,
        _format_antispam_settings(antispam),
        admin_support_antispam_keyboard(antispam),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_SPAM_PREFIX))
async def handle_admin_support_settings_update(callback: CallbackQuery, session: AsyncSession) -> None:
    remainder = callback.data.removeprefix(ADMIN_SUPPORT_SPAM_PREFIX)
    try:
        field, delta_raw = remainder.split(":")
    except ValueError:
        await callback.answer()
        return
    if field == "noop":
        await callback.answer()
        return
    try:
        delta = int(delta_raw)
    except ValueError:
        await callback.answer("Invalid change.", show_alert=True)
        return
    if delta == 0:
        await callback.answer()
        return
    config_service = ConfigService(session)
    settings = await config_service.get_support_antispam_settings()
    if field == "open":
        settings.max_open_tickets = max(0, settings.max_open_tickets + delta)
    elif field == "win":
        settings.window_minutes = max(0, settings.window_minutes + delta)
    elif field == "winmax":
        settings.max_tickets_per_window = max(0, settings.max_tickets_per_window + delta)
    elif field == "delay":
        settings.min_reply_interval_seconds = max(0, settings.min_reply_interval_seconds + delta)
    else:
        await callback.answer()
        return
    settings = await config_service.save_support_antispam_settings(settings)
    await _safe_edit_message(
        callback.message,
        _format_antispam_settings(settings),
        admin_support_antispam_keyboard(settings),
    )
    await callback.answer("Updated.")


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
    ticket = await service.ensure_order_loaded(ticket)
    ticket = await service.ensure_user_loaded(ticket)
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
    ticket = await service.ensure_order_loaded(ticket)
    ticket = await service.ensure_user_loaded(ticket)
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
    ticket = await service.ensure_order_loaded(ticket)
    ticket = await service.ensure_user_loaded(ticket)

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
                reply_markup=support_ticket_notification_keyboard(ticket),
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
    try:
        ticket_id, status_code = remainder.split(":", 1)
    except ValueError:
        await callback.answer("Invalid status.", show_alert=True)
        return
    status = decode_status_code(status_code)
    if status is None:
        await callback.answer("Invalid status.", show_alert=True)
        return
    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(ticket_id)
    if ticket is None:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    ticket = await service.ensure_order_loaded(ticket)
    ticket = await service.ensure_user_loaded(ticket)
    previous_status = ticket.status
    await service.set_status(ticket, status)
    if status == SupportTicketStatus.RESOLVED and previous_status != SupportTicketStatus.RESOLVED:
        resolution_text = _format_ticket_resolved_notification(ticket)
        bot = callback.message.bot if callback.message else None
        user_chat_id = getattr(getattr(ticket, "user", None), "telegram_id", None)
        if bot and user_chat_id and user_chat_id != callback.from_user.id:
            try:
                await bot.send_message(
                    user_chat_id,
                    resolution_text,
                    reply_markup=support_ticket_notification_keyboard(ticket),
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
        await service.add_system_message(
            ticket,
            body="Ticket marked as resolved.",
            payload={
                "status": status.value,
                "admin_id": callback.from_user.id,
            },
        )
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
    ticket = await service.ensure_order_loaded(ticket)
    ticket = await service.ensure_user_loaded(ticket)
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
    ticket = await service.ensure_order_loaded(ticket)
    ticket = await service.ensure_user_loaded(ticket)
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


@router.callback_query(F.data.startswith(ADMIN_SUPPORT_ORDER_ACTION_PREFIX))
async def handle_admin_support_order_action(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    remainder = callback.data.removeprefix(ADMIN_SUPPORT_ORDER_ACTION_PREFIX)
    try:
        action, ticket_id = remainder.split(":", 1)
    except ValueError:
        await callback.answer("Invalid action.", show_alert=True)
        return

    service = SupportService(session)
    ticket = await service.get_ticket_by_public_id(ticket_id)
    if ticket is None:
        await callback.answer("Ticket not found.", show_alert=True)
        return
    ticket = await service.ensure_order_loaded(ticket)
    ticket = await service.ensure_user_loaded(ticket)

    message_text = None
    if action == "pause":
        changed = await service.pause_ticket_order(ticket, reason=f"ticket:{ticket.public_id}")
        if changed:
            await service.add_system_message(
                ticket,
                body="Service timer paused by admin.",
                payload={"admin_id": callback.from_user.id},
            )
            message_text = "Service timer paused."
        else:
            message_text = "Unable to pause (already paused or no active duration)."
    elif action == "resume":
        changed = await service.resume_ticket_order(ticket)
        if changed:
            await service.add_system_message(
                ticket,
                body="Service timer resumed by admin.",
                payload={"admin_id": callback.from_user.id},
            )
            message_text = "Service timer resumed."
        else:
            message_text = "Unable to resume (timer not paused or no active duration)."
    else:
        await callback.answer("Unknown action.", show_alert=True)
        return

    data = await state.get_data()
    filter_code = data.get("support_filter", "open")
    page = int(data.get("support_page", 0))
    await _safe_edit_message(
        callback.message,
        _format_admin_ticket_detail(ticket),
        admin_support_ticket_keyboard(ticket, admin_id=callback.from_user.id, filter_code=filter_code, page=page),
    )
    await callback.answer(message_text or "Done.")


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


def _format_antispam_settings(settings: ConfigService.SupportAntiSpamSettings) -> str:
    lines = ["<b>Spam protection</b>", "Configure ticket limits to reduce spam. Use 0 to disable a rule.", ""]
    max_open = _format_limit_value(settings.max_open_tickets, "ticket")
    if settings.max_tickets_per_window > 0 and settings.window_minutes > 0:
        window_limit = (
            f"{_format_limit_value(settings.max_tickets_per_window, 'ticket')} every "
            f"{_format_limit_value(settings.window_minutes, 'minute')}"
        )
    else:
        window_limit = "disabled"
    message_delay = _format_limit_value(settings.min_reply_interval_seconds, "second")
    window_length = _format_limit_value(settings.window_minutes, "minute")
    lines.append(f"Max open tickets per user: {max_open}")
    lines.append(f"Ticket window length: {window_length}")
    lines.append(f"New tickets per window: {window_limit}")
    lines.append(f"Minimum delay between user messages: {message_delay}")
    return "\n".join(lines)


def _format_limit_value(value: int, unit: str) -> str:
    if value <= 0:
        return "disabled"
    suffix = unit if value == 1 else f"{unit}s"
    return f"{value} {suffix}"


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
        service_lines = _format_order_service_lines(ticket.order)
        if service_lines:
            lines.extend(service_lines)
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


def _format_ticket_resolved_notification(ticket: SupportTicket) -> str:
    lines = [
        "<b>Support update</b>",
        f"Ticket: <code>{ticket.public_id}</code>",
        "",
        "Your ticket has been marked as resolved. Reply in this conversation if you still need help.",
    ]
    return "\n".join(lines)


def _format_order_service_lines(order) -> list[str]:
    if not _order_has_duration(order):
        return []
    lines: list[str] = []
    if order.service_started_at is None:
        lines.append("Service status: Not started yet.")
        return lines
    status = "Paused" if order.service_paused_at else "Active"
    lines.append(f"Service status: {status}")
    remaining = _calculate_remaining_seconds(order)
    if remaining is not None:
        lines.append(f"Time remaining: {_humanize_seconds(remaining)}")
        expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=remaining)
        lines.append(f"ETA expiry: {expires_at:%Y-%m-%d %H:%M UTC}")
    return lines


def _order_has_duration(order) -> bool:
    value = getattr(order, "service_duration_days", None)
    return bool(value and value > 0)


def _calculate_remaining_seconds(order) -> int | None:
    if not _order_has_duration(order):
        return None
    duration_days = order.service_duration_days or 0
    started_at = order.service_started_at
    if started_at is None:
        return duration_days * 86400
    elapsed = (datetime.now(tz=timezone.utc) - _ensure_dt(started_at)).total_seconds()
    paused_total = int(getattr(order, "service_paused_total_seconds", 0) or 0)
    if getattr(order, "service_paused_at", None):
        elapsed -= (datetime.now(tz=timezone.utc) - _ensure_dt(order.service_paused_at)).total_seconds()
    elapsed -= paused_total
    total_seconds = duration_days * 86400
    remaining = int(total_seconds - max(elapsed, 0))
    return max(remaining, 0)


def _humanize_seconds(seconds: int) -> str:
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{sec}s")
    return " ".join(parts)


def _ensure_dt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _safe_edit_message(message, text: str, reply_markup) -> None:
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception:
        await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)
