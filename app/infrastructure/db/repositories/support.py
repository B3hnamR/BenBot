from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import joinedload

from app.core.enums import SupportAuthorRole, SupportTicketPriority, SupportTicketStatus
from app.infrastructure.db.models import Order, SupportMessage, SupportTicket

from .base import BaseRepository


class SupportRepository(BaseRepository):
    async def create_ticket(
        self,
        *,
        user_id: int,
        subject: str,
        category: str | None = None,
        priority: SupportTicketPriority = SupportTicketPriority.NORMAL,
        order_id: int | None = None,
        assigned_admin_id: int | None = None,
        meta: dict | None = None,
    ) -> SupportTicket:
        ticket = SupportTicket(
            user_id=user_id,
            subject=subject,
            category=category,
            priority=priority,
            order_id=order_id,
            assigned_admin_id=assigned_admin_id,
            meta=meta,
            last_activity_at=datetime.now(tz=timezone.utc),
        )
        await self.add(ticket)
        return ticket

    async def add_message(
        self,
        ticket: SupportTicket,
        *,
        role: SupportAuthorRole,
        author_id: int | None,
        body: str,
        payload: dict | None = None,
    ) -> SupportMessage:
        message = SupportMessage(
            ticket=ticket,
            author_role=role,
            author_id=author_id,
            body=body,
            payload=payload,
        )
        ticket.last_activity_at = datetime.now(tz=timezone.utc)
        await self.add(message)
        return message

    async def get_by_public_id(self, public_id: str) -> SupportTicket | None:
        result = await self.session.execute(
            select(SupportTicket)
            .options(
                joinedload(SupportTicket.user),
                joinedload(SupportTicket.order).joinedload(Order.product),
                joinedload(SupportTicket.messages),
            )
            .where(SupportTicket.public_id == public_id)
        )
        return result.unique().scalar_one_or_none()

    async def paginate_for_user(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[SupportTicket], bool]:
        stmt = (
            select(SupportTicket)
            .options(joinedload(SupportTicket.order))
            .where(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.last_activity_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        result = await self.session.execute(stmt)
        tickets = list(result.scalars().unique().all())
        has_more = len(tickets) > limit
        return tickets[:limit], has_more

    async def paginate_for_admin(
        self,
        *,
        limit: int,
        offset: int = 0,
        statuses: Iterable[SupportTicketStatus] | None = None,
        priorities: Iterable[SupportTicketPriority] | None = None,
        assigned_admin_id: int | None = None,
        category: str | None = None,
        search: str | None = None,
        only_open: bool = False,
    ) -> tuple[list[SupportTicket], bool]:
        stmt: Select[tuple[SupportTicket]] = (
            select(SupportTicket)
            .options(
                joinedload(SupportTicket.user),
                joinedload(SupportTicket.order).joinedload(Order.product),
            )
            .order_by(SupportTicket.last_activity_at.desc())
        )

        if only_open:
            stmt = stmt.where(SupportTicket.status.in_(
                [SupportTicketStatus.OPEN, SupportTicketStatus.AWAITING_ADMIN, SupportTicketStatus.AWAITING_USER]
            ))
        if statuses:
            stmt = stmt.where(SupportTicket.status.in_(list(statuses)))
        if priorities:
            stmt = stmt.where(SupportTicket.priority.in_(list(priorities)))
        if assigned_admin_id is not None:
            if assigned_admin_id < 0:
                stmt = stmt.where(SupportTicket.assigned_admin_id.is_(None))
            else:
                stmt = stmt.where(SupportTicket.assigned_admin_id == assigned_admin_id)
        if category:
            stmt = stmt.where(SupportTicket.category == category)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(SupportTicket.subject).like(like),
                    func.lower(SupportTicket.public_id).like(like),
                )
            )

        stmt = stmt.offset(offset).limit(limit + 1)
        result = await self.session.execute(stmt)
        tickets = list(result.scalars().unique().all())
        has_more = len(tickets) > limit
        return tickets[:limit], has_more

    async def set_status(self, ticket: SupportTicket, status: SupportTicketStatus) -> SupportTicket:
        ticket.status = status
        ticket.last_activity_at = datetime.now(tz=timezone.utc)
        return ticket

    async def set_priority(self, ticket: SupportTicket, priority: SupportTicketPriority) -> SupportTicket:
        ticket.priority = priority
        return ticket

    async def assign_admin(self, ticket: SupportTicket, admin_id: int | None) -> SupportTicket:
        ticket.assigned_admin_id = admin_id
        return ticket

    async def update_meta(self, ticket: SupportTicket, updates: dict) -> SupportTicket:
        meta = dict(ticket.meta or {})
        meta.update(updates)
        ticket.meta = meta
        return ticket

    async def status_counts(self) -> dict[SupportTicketStatus, int]:
        result = await self.session.execute(
            select(SupportTicket.status, func.count()).group_by(SupportTicket.status)
        )
        return {status: count for status, count in result.all()}

    async def priority_counts(self) -> dict[SupportTicketPriority, int]:
        result = await self.session.execute(
            select(SupportTicket.priority, func.count()).group_by(SupportTicket.priority)
        )
        return {priority: count for priority, count in result.all()}
