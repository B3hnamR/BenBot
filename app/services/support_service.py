from __future__ import annotations

from dataclasses import dataclass
import math
from datetime import datetime, timezone, timedelta
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from typing import TYPE_CHECKING

from app.core.enums import SupportAuthorRole, SupportTicketPriority, SupportTicketStatus
from app.infrastructure.db.models import Order, SupportTicket
from app.infrastructure.db.repositories import OrderRepository, SupportRepository, UserRepository
from app.services.order_duration_service import OrderDurationService
from app.services.order_service import OrderService

if TYPE_CHECKING:
    from app.services.config_service import ConfigService


@dataclass(slots=True)
class TicketFilters:
    statuses: set[SupportTicketStatus] | None = None
    priorities: set[SupportTicketPriority] | None = None
    assigned_admin_id: int | None = None
    category: str | None = None
    search: str | None = None
    only_open: bool = False


class SupportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tickets = SupportRepository(session)
        self._orders = OrderRepository(session)
        self._users = UserRepository(session)
        self._order_service = OrderService(session)
        self._duration = OrderDurationService(session)

    async def create_ticket(
        self,
        *,
        user_id: int,
        subject: str,
        body: str,
        category: str | None = None,
        priority: SupportTicketPriority = SupportTicketPriority.NORMAL,
        order_id: int | None = None,
        assigned_admin_id: int | None = None,
        meta: dict | None = None,
        author_telegram_id: int | None = None,
    ) -> SupportTicket:
        ticket = await self._tickets.create_ticket(
            user_id=user_id,
            subject=subject,
            category=category,
            priority=priority,
            order_id=order_id,
            assigned_admin_id=assigned_admin_id,
            meta=meta,
        )
        message = await self._tickets.add_message(
            ticket,
            role=SupportAuthorRole.USER,
            author_id=author_telegram_id,
            body=body,
        )
        _append_ticket_message(ticket, message)
        await self._tickets.set_status(ticket, SupportTicketStatus.AWAITING_ADMIN)
        return ticket

    async def add_user_message(
        self,
        ticket: SupportTicket,
        *,
        body: str,
        author_telegram_id: int | None,
    ) -> None:
        message = await self._tickets.add_message(
            ticket,
            role=SupportAuthorRole.USER,
            author_id=author_telegram_id,
            body=body,
        )
        _append_ticket_message(ticket, message)
        await self._tickets.set_status(ticket, SupportTicketStatus.AWAITING_ADMIN)

    async def add_admin_message(
        self,
        ticket: SupportTicket,
        *,
        body: str,
        admin_telegram_id: int | None,
        payload: dict | None = None,
    ) -> None:
        message = await self._tickets.add_message(
            ticket,
            role=SupportAuthorRole.ADMIN,
            author_id=admin_telegram_id,
            body=body,
            payload=payload,
        )
        _append_ticket_message(ticket, message)
        await self._tickets.set_status(ticket, SupportTicketStatus.AWAITING_USER)

    async def get_ticket_by_public_id(self, public_id: str) -> SupportTicket | None:
        return await self._tickets.get_by_public_id(public_id)

    async def paginate_user_tickets(
        self,
        user_id: int,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[SupportTicket], bool]:
        offset = max(page, 0) * page_size
        return await self._tickets.paginate_for_user(user_id, limit=page_size, offset=offset)

    async def paginate_admin_tickets(
        self,
        *,
        page: int,
        page_size: int,
        filters: TicketFilters | None = None,
    ) -> tuple[list[SupportTicket], bool]:
        filters = filters or TicketFilters()
        offset = max(page, 0) * page_size
        return await self._tickets.paginate_for_admin(
            limit=page_size,
            offset=offset,
            statuses=filters.statuses,
            priorities=filters.priorities,
            assigned_admin_id=filters.assigned_admin_id,
            category=filters.category,
            search=filters.search,
            only_open=filters.only_open,
        )

    async def set_status(self, ticket: SupportTicket, status: SupportTicketStatus) -> SupportTicket:
        return await self._tickets.set_status(ticket, status)

    async def set_priority(self, ticket: SupportTicket, priority: SupportTicketPriority) -> SupportTicket:
        return await self._tickets.set_priority(ticket, priority)

    async def assign_admin(self, ticket: SupportTicket, admin_id: int | None) -> SupportTicket:
        return await self._tickets.assign_admin(ticket, admin_id)

    async def status_counts(self) -> dict[SupportTicketStatus, int]:
        return await self._tickets.status_counts()

    async def priority_counts(self) -> dict[SupportTicketPriority, int]:
        return await self._tickets.priority_counts()

    async def touch(self, ticket: SupportTicket) -> None:
        ticket.last_activity_at = datetime.now(tz=timezone.utc)

    async def ensure_order_loaded(self, ticket: SupportTicket) -> SupportTicket:
        if ticket.order_id is not None:
            if ticket.order is None:
                ticket.order = await self._orders.get_by_id(ticket.order_id)  # type: ignore[attr-defined]
            if ticket.order is not None:
                missing_attrs = []
                if "product" not in ticket.order.__dict__:
                    missing_attrs.append("product")
                if "pause_periods" not in ticket.order.__dict__:
                    missing_attrs.append("pause_periods")
                if missing_attrs:
                    await self._session.refresh(ticket.order, attribute_names=missing_attrs)
        return ticket

    async def ensure_user_loaded(self, ticket: SupportTicket) -> SupportTicket:
        if ticket.user is None:
            ticket.user = await self._users.get_by_id(ticket.user_id)  # type: ignore[attr-defined]
        return ticket

    async def pause_ticket_order(self, ticket: SupportTicket, *, reason: str | None = None) -> bool:
        await self.ensure_order_loaded(ticket)
        order = ticket.order
        if order is None or not self._duration.has_duration(order):
            return False
        changed = await self._duration.pause(order, reason=reason)
        if not changed:
            return False
        await self._tickets.session.flush()
        return True

    async def resume_ticket_order(self, ticket: SupportTicket) -> bool:
        await self.ensure_order_loaded(ticket)
        order = ticket.order
        if order is None or not self._duration.has_duration(order):
            return False
        changed = await self._duration.resume(order)
        if not changed:
            return False
        await self._tickets.session.flush()
        return True

    async def create_replacement_order(
        self,
        ticket: SupportTicket,
        *,
        actor: str | None = None,
    ) -> Order | None:
        await self.ensure_order_loaded(ticket)
        if ticket.order is None:
            return None
        replacement = await self._order_service.create_replacement_order(
            ticket.order,
            actor=actor,
        )
        return replacement

    async def add_system_message(
        self,
        ticket: SupportTicket,
        *,
        body: str,
        payload: dict | None = None,
    ) -> None:
        message = await self._tickets.add_message(
            ticket,
            role=SupportAuthorRole.SYSTEM,
            author_id=None,
            body=body,
            payload=payload,
        )
        _append_ticket_message(ticket, message)

    async def check_new_ticket_limits(
        self,
        user_id: int,
        settings: "ConfigService.SupportAntiSpamSettings",
    ) -> str | None:
        if settings.max_open_tickets > 0:
            open_count = await self._tickets.count_open_by_user(user_id)
            if open_count >= settings.max_open_tickets:
                return (
                    f"You already have {open_count} open ticket(s). "
                    "Please resolve one before creating another."
                )
        if settings.max_tickets_per_window > 0 and settings.window_minutes > 0:
            window_start = datetime.now(tz=timezone.utc) - timedelta(minutes=settings.window_minutes)
            recent = await self._tickets.count_created_since(user_id, window_start)
            if recent >= settings.max_tickets_per_window:
                return (
                    "You've reached the limit for new tickets in the current window. "
                    "Please wait a bit before opening another request."
                )
        return None

    async def check_user_message_rate(
        self,
        user_id: int,
        settings: "ConfigService.SupportAntiSpamSettings",
        *,
        ticket_id: int | None = None,
    ) -> str | None:
        if settings.min_reply_interval_seconds <= 0:
            return None
        last_global = await self._tickets.last_user_message_time(user_id)
        last_ticket = None
        if ticket_id is not None:
            last_ticket = await self._tickets.last_user_message_time_in_ticket(ticket_id)
        timestamps = [ts for ts in (last_global, last_ticket) if ts is not None]
        if not timestamps:
            return None
        latest = max(_ensure_aware(ts) for ts in timestamps)
        elapsed = (datetime.now(tz=timezone.utc) - latest).total_seconds()
        if elapsed < settings.min_reply_interval_seconds:
            remaining = int(
                max(1, math.ceil(settings.min_reply_interval_seconds - elapsed))
            )
            return f"Please wait {remaining} more second(s) before sending another support message."
        return None


def _append_ticket_message(ticket: SupportTicket, message) -> None:
    current = ticket.__dict__.get("messages")
    if current is None:
        set_committed_value(ticket, "messages", [message])
    else:
        current.append(message)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
