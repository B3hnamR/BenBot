from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Order, OrderPausePeriod


class OrderDurationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(self, order: Order, *, duration_days: int | None) -> None:
        if duration_days is None or duration_days <= 0:
            order.service_duration_days = None
            order.service_started_at = None
            order.service_paused_total_seconds = 0
            order.service_paused_at = None
            return
        order.service_duration_days = duration_days
        order.service_started_at = datetime.now(tz=timezone.utc)
        order.service_paused_total_seconds = 0
        order.service_paused_at = None

    async def pause(self, order: Order, *, reason: str | None = None) -> bool:
        if order.service_paused_at is not None:
            return False
        if not self._has_duration(order):
            return False
        now = datetime.now(tz=timezone.utc)
        order.service_paused_at = now
        period = OrderPausePeriod(
            order_id=order.id,
            started_at=now,
            reason=reason,
        )
        self._session.add(period)
        await self._session.flush()
        return True

    async def resume(self, order: Order) -> bool:
        if order.service_paused_at is None:
            return False
        now = datetime.now(tz=timezone.utc)
        paused_seconds = int((now - order.service_paused_at).total_seconds())
        order.service_paused_total_seconds = int(order.service_paused_total_seconds or 0) + max(paused_seconds, 0)
        order.service_paused_at = None

        period = next((p for p in order.pause_periods if getattr(p, "ended_at", None) is None), None)
        if period is not None:
            period.ended_at = now
        return True

    def remaining_seconds(self, order: Order) -> int | None:
        if not self._has_duration(order):
            return None
        started_at = order.service_started_at
        duration_days = order.service_duration_days or 0
        if started_at is None:
            return duration_days * 86400
        elapsed = (datetime.now(tz=timezone.utc) - started_at).total_seconds()
        paused_total = int(order.service_paused_total_seconds or 0)
        if order.service_paused_at is not None:
            elapsed -= (datetime.now(tz=timezone.utc) - order.service_paused_at).total_seconds()
        elapsed -= paused_total
        total_seconds = duration_days * 86400
        remaining = int(total_seconds - max(elapsed, 0))
        return max(remaining, 0)

    def expires_at(self, order: Order) -> datetime | None:
        if not self._has_duration(order):
            return None
        remaining = self.remaining_seconds(order)
        if remaining is None:
            return None
        return datetime.now(tz=timezone.utc) + timedelta(seconds=remaining)

    def is_paused(self, order: Order) -> bool:
        return bool(order.service_paused_at)

    def has_duration(self, order: Order) -> bool:
        return self._has_duration(order)

    @staticmethod
    def _has_duration(order: Order) -> bool:
        return bool(order.service_duration_days and order.service_duration_days > 0)
