from __future__ import annotations

from typing import Sequence, TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.keyboards.admin import AdminMenuCallback
from app.core.enums import SupportTicketPriority, SupportTicketStatus
from app.infrastructure.db.models import SupportTicket

if TYPE_CHECKING:
    from app.services.config_service import ConfigService

ADMIN_SUPPORT_MENU_OPEN = "admin:sup:open"
ADMIN_SUPPORT_MENU_ALL = "admin:sup:all"
ADMIN_SUPPORT_MENU_ASSIGNED = "admin:sup:mine"
ADMIN_SUPPORT_MENU_AWAITING_USER = "admin:sup:await_user"
ADMIN_SUPPORT_SETTINGS = "admin:sup:settings"

ADMIN_SUPPORT_LIST_PREFIX = "admin:sup:list:"
ADMIN_SUPPORT_VIEW_PREFIX = "admin:sup:view:"
ADMIN_SUPPORT_REPLY_PREFIX = "admin:sup:reply:"
ADMIN_SUPPORT_STATUS_PREFIX = "as:st:"
ADMIN_SUPPORT_ASSIGN_PREFIX = "admin:sup:assign:"
ADMIN_SUPPORT_PRIORITY_PREFIX = "admin:sup:priority:"
ADMIN_SUPPORT_SPAM_PREFIX = "as:sp:"

_STATUS_CODE_MAP: dict[SupportTicketStatus, str] = {
    SupportTicketStatus.OPEN: "op",
    SupportTicketStatus.RESOLVED: "rs",
    SupportTicketStatus.AWAITING_USER: "au",
    SupportTicketStatus.AWAITING_ADMIN: "aa",
    SupportTicketStatus.ARCHIVED: "ar",
}
_STATUS_CODE_REVERSE: dict[str, SupportTicketStatus] = {code: status for status, code in _STATUS_CODE_MAP.items()}


def encode_status_code(status: SupportTicketStatus) -> str:
    return _STATUS_CODE_MAP[status]


def decode_status_code(code: str) -> SupportTicketStatus | None:
    return _STATUS_CODE_REVERSE.get(code)


def admin_support_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Open tickets", callback_data=ADMIN_SUPPORT_MENU_OPEN)
    builder.button(text="Assigned to me", callback_data=ADMIN_SUPPORT_MENU_ASSIGNED)
    builder.button(text="Awaiting customer", callback_data=ADMIN_SUPPORT_MENU_AWAITING_USER)
    builder.button(text="All tickets", callback_data=ADMIN_SUPPORT_MENU_ALL)
    builder.button(text="Spam guard", callback_data=ADMIN_SUPPORT_SETTINGS)
    builder.button(text="Back", callback_data="admin:back_to_main")
    builder.adjust(1)
    return builder.as_markup()


def admin_support_list_keyboard(
    tickets: Sequence[SupportTicket],
    *,
    filter_code: str,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ticket in tickets:
        builder.button(
            text=_ticket_summary(ticket),
            callback_data=f"{ADMIN_SUPPORT_VIEW_PREFIX}{ticket.public_id}",
        )
    nav_buttons: list[InlineKeyboardButton] = []
    prefix = f"{ADMIN_SUPPORT_LIST_PREFIX}{filter_code}:"
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text="◀️ Prev",
                callback_data=f"{prefix}{page - 1}",
            )
        )
    nav_buttons.append(
        InlineKeyboardButton(
            text="Refresh",
            callback_data=f"{prefix}{page}",
        )
    )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="▶️ Next",
                callback_data=f"{prefix}{page + 1}",
            )
        )
    builder.row(*nav_buttons)
    builder.button(text="Back", callback_data="admin:manage_support")
    builder.adjust(1)
    return builder.as_markup()


def admin_support_ticket_keyboard(
    ticket: SupportTicket,
    *,
    admin_id: int | None,
    filter_code: str,
    page: int,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Reply", callback_data=f"{ADMIN_SUPPORT_REPLY_PREFIX}{ticket.public_id}")

    if ticket.assigned_admin_id == admin_id:
        builder.button(
            text="Release ticket",
            callback_data=f"{ADMIN_SUPPORT_ASSIGN_PREFIX}{ticket.public_id}:none",
        )
    else:
        builder.button(
            text="Assign to me",
            callback_data=f"{ADMIN_SUPPORT_ASSIGN_PREFIX}{ticket.public_id}:me",
        )

    if ticket.status in {SupportTicketStatus.RESOLVED, SupportTicketStatus.ARCHIVED}:
        builder.button(
            text="Reopen",
            callback_data=f"{ADMIN_SUPPORT_STATUS_PREFIX}{ticket.public_id}:{encode_status_code(SupportTicketStatus.OPEN)}",
        )
    else:
        builder.button(
            text="Mark resolved",
            callback_data=f"{ADMIN_SUPPORT_STATUS_PREFIX}{ticket.public_id}:{encode_status_code(SupportTicketStatus.RESOLVED)}",
        )
        builder.button(
            text="Awaiting customer",
            callback_data=f"{ADMIN_SUPPORT_STATUS_PREFIX}{ticket.public_id}:{encode_status_code(SupportTicketStatus.AWAITING_USER)}",
        )
        builder.button(
            text="Awaiting admin",
            callback_data=f"{ADMIN_SUPPORT_STATUS_PREFIX}{ticket.public_id}:{encode_status_code(SupportTicketStatus.AWAITING_ADMIN)}",
        )

    next_priority = _next_priority(ticket.priority)
    builder.button(
        text=f"Priority: {ticket.priority.value.title()} (set {next_priority.value.title()})",
        callback_data=f"{ADMIN_SUPPORT_PRIORITY_PREFIX}{ticket.public_id}:{next_priority.value}",
    )

    builder.button(
        text="Back",
        callback_data=f"{ADMIN_SUPPORT_LIST_PREFIX}{filter_code}:{max(page, 0)}",
    )
    builder.adjust(1)
    return builder.as_markup()


def _ticket_summary(ticket: SupportTicket) -> str:
    status = ticket.status.value.replace("_", " ").title()
    subject = ticket.subject[:32]
    user_text = f"u{ticket.user.telegram_id if ticket.user else ticket.user_id}"
    return f"{status} • {subject} • {user_text}"


def _next_priority(current: SupportTicketPriority) -> SupportTicketPriority:
    order = [
        SupportTicketPriority.LOW,
        SupportTicketPriority.NORMAL,
        SupportTicketPriority.HIGH,
        SupportTicketPriority.URGENT,
    ]
    idx = order.index(current)
    return order[(idx + 1) % len(order)]


def admin_support_antispam_keyboard(
    settings: "ConfigService.SupportAntiSpamSettings",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="Max open -",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}open:-1",
        ),
        InlineKeyboardButton(
            text="Max open +",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}open:+1",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="Window min -5",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}win:-5",
        ),
        InlineKeyboardButton(
            text="Window min +5",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}win:+5",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="Per window -",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}winmax:-1",
        ),
        InlineKeyboardButton(
            text="Per window +",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}winmax:+1",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="Delay s -5",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}delay:-5",
        ),
        InlineKeyboardButton(
            text="Delay s +5",
            callback_data=f"{ADMIN_SUPPORT_SPAM_PREFIX}delay:+5",
        ),
    )
    builder.button(
        text="Back",
        callback_data=AdminMenuCallback.MANAGE_SUPPORT.value,
    )
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()
