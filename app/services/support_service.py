from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SupportAuthorRole, SupportTicketPriority, SupportTicketStatus
from app.infrastructure.db.models import SupportTicket
from app.infrastructure.db.repositories import OrderRepository, SupportRepository, UserRepository


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
        await self._tickets.add_message(
            ticket,
            role=SupportAuthorRole.USER,
            author_id=author_telegram_id,
            body=body,
        )
        await self._tickets.set_status(ticket, SupportTicketStatus.AWAITING_ADMIN)
        return ticket

    async def add_user_message(
        self,
        ticket: SupportTicket,
        *,
        body: str,
        author_telegram_id: int | None,
    ) -> None:
        await self._tickets.add_message(
            ticket,
            role=SupportAuthorRole.USER,
            author_id=author_telegram_id,
            body=body,
        )
        await self._tickets.set_status(ticket, SupportTicketStatus.AWAITING_ADMIN)

    async def add_admin_message(
        self,
        ticket: SupportTicket,
        *,
        body: str,
        admin_telegram_id: int | None,
        payload: dict | None = None,
    ) -> None:
        await self._tickets.add_message(
            ticket,
            role=SupportAuthorRole.ADMIN,
            author_id=admin_telegram_id,
            body=body,
            payload=payload,
        )
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
        if ticket.order is None and ticket.order_id is not None:
            ticket.order = await self._orders.get_by_id(ticket.order_id)  # type: ignore[attr-defined]
        return ticket

    async def ensure_user_loaded(self, ticket: SupportTicket) -> SupportTicket:
        if ticket.user is None:
            ticket.user = await self._users.get_by_id(ticket.user_id)  # type: ignore[attr-defined]
        return ticket
