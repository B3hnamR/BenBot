from __future__ import annotations

from typing import Iterable, Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.enums import SupportTicketStatus
from app.infrastructure.db.models import Order, SupportTicket

SUPPORT_NEW_TICKET = "support:new"
SUPPORT_MY_TICKETS = "support:list"
SUPPORT_BACK_MAIN = "support:back_main"
SUPPORT_CANCEL = "support:cancel"

SUPPORT_CATEGORY_PREFIX = "support:category:"
SUPPORT_ORDER_SELECT_PREFIX = "support:order_select:"
SUPPORT_ORDER_CREATE_PREFIX = "support:order:"
SUPPORT_ORDER_PAGE_PREFIX = "support:order_page:"

SUPPORT_TICKET_LIST_PAGE_PREFIX = "support:tickets:"
SUPPORT_TICKET_VIEW_PREFIX = "support:view:"
SUPPORT_TICKET_REPLY_PREFIX = "support:reply:"
SUPPORT_TICKET_RESOLVE_PREFIX = "support:resolve:"
SUPPORT_TICKET_REOPEN_PREFIX = "support:reopen:"


def support_main_keyboard(has_tickets: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🆕 New support ticket", callback_data=SUPPORT_NEW_TICKET)
    if has_tickets:
        builder.button(text="🗂 My tickets", callback_data=SUPPORT_MY_TICKETS)
    builder.button(text="Back to menu", callback_data=SUPPORT_BACK_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def support_categories_keyboard(categories: Iterable[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(text=category, callback_data=f"{SUPPORT_CATEGORY_PREFIX}{category}")
    builder.button(text="Skip", callback_data=f"{SUPPORT_CATEGORY_PREFIX}-")
    builder.button(text="Cancel", callback_data=SUPPORT_CANCEL)
    builder.adjust(2)
    return builder.as_markup()


def support_orders_keyboard(
    orders: Sequence[Order],
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        product_name = getattr(order.product, "name", "Order")
        builder.button(
            text=f"{product_name[:32]} • {order.total_amount} {order.currency}",
            callback_data=f"{SUPPORT_ORDER_SELECT_PREFIX}{order.public_id}",
        )
    nav_buttons: list[InlineKeyboardButton] = []
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"{SUPPORT_ORDER_PAGE_PREFIX}{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text="Skip",
            callback_data=f"{SUPPORT_ORDER_SELECT_PREFIX}-",
        )
    )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️ Next",
                callback_data=f"{SUPPORT_ORDER_PAGE_PREFIX}{page + 1}",
            )
        )
    builder.row(*nav_buttons)
    builder.button(text="Cancel", callback_data=SUPPORT_CANCEL)
    builder.adjust(1)
    return builder.as_markup()


def support_ticket_list_keyboard(
    tickets: Sequence[SupportTicket],
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        label = _ticket_summary_line(ticket)
        builder.button(text=label, callback_data=f"{SUPPORT_TICKET_VIEW_PREFIX}{ticket.public_id}")
    nav_buttons: list[InlineKeyboardButton] = []
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"{SUPPORT_TICKET_LIST_PAGE_PREFIX}{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text="Refresh",
            callback_data=f"{SUPPORT_TICKET_LIST_PAGE_PREFIX}{page}",
        )
    )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️ Next",
                callback_data=f"{SUPPORT_TICKET_LIST_PAGE_PREFIX}{page + 1}",
            )
        )
    builder.row(*nav_buttons)
    builder.button(text="Back", callback_data=SUPPORT_BACK_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def support_ticket_detail_keyboard(ticket: SupportTicket) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Reply", callback_data=f"{SUPPORT_TICKET_REPLY_PREFIX}{ticket.public_id}")
    if ticket.status in {SupportTicketStatus.RESOLVED, SupportTicketStatus.ARCHIVED}:
        builder.button(text="Reopen", callback_data=f"{SUPPORT_TICKET_REOPEN_PREFIX}{ticket.public_id}")
    else:
        builder.button(text="Mark resolved", callback_data=f"{SUPPORT_TICKET_RESOLVE_PREFIX}{ticket.public_id}")
    builder.button(text="Back to tickets", callback_data=SUPPORT_MY_TICKETS)
    builder.button(text="Back to menu", callback_data=SUPPORT_BACK_MAIN)
    builder.adjust(1)
    return builder.as_markup()


def _ticket_summary_line(ticket: SupportTicket) -> str:
    status = ticket.status.value.replace("_", " ").title()
    subject = ticket.subject[:40]
    if ticket.order is not None:
        return f"{status} • {subject} • #{ticket.order.public_id[:6]}"
    return f"{status} • {subject}"
