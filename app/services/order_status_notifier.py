from __future__ import annotations

from typing import Mapping

from aiogram import Bot

from app.core.logging import get_logger
from app.infrastructure.db.models import Order
from app.services.timeline_status_service import TimelineStatusRegistry

log = get_logger(__name__)

DEFAULT_STATUS_MESSAGES: Mapping[str, str] = {
    "processing": (
        "Order <code>{order_id}</code> is now being processed.\n"
        "We'll let you know as soon as it ships."
    ),
    "shipping": (
        "Great news! Order <code>{order_id}</code> is on its way.\n"
        "We'll notify you once it has been delivered."
    ),
    "delivered": (
        "Order <code>{order_id}</code> has been delivered.\n"
        "If you need anything else, just let us know."
    ),
}


async def notify_user_status(
    bot: Bot,
    order: Order,
    status: str,
    *,
    note: str | None = None,
) -> bool:
    definition = TimelineStatusRegistry.get(status)
    template = None
    if definition and definition.user_message:
        template = definition.user_message
    if template is None:
        template = DEFAULT_STATUS_MESSAGES.get(status)
    if template is None:
        template = "Order <code>{order_id}</code> status updated: {status_label}."

    user = getattr(order, "user", None)
    chat_id = getattr(user, "telegram_id", None)
    if chat_id is None:
        return False

    status_label = definition.label if definition else (status.replace("_", " ").title() if status else "Update")
    message_lines = [
        template.format(
            order_id=order.public_id,
            status=status,
            status_label=status_label,
        )
    ]
    if note:
        message_lines.append("")
        message_lines.append(note)

    text = "\n".join(message_lines)
    try:
        await bot.send_message(chat_id, text)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "order_status_notification_failed",
            order_id=order.id,
            status=status,
            error=str(exc),
        )
        return False

    log.info(
        "order_status_notification_sent",
        order_id=order.id,
        status=status,
    )
    return True
