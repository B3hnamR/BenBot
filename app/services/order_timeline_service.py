from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Order, OrderTimeline
from app.infrastructure.db.repositories.order_timeline import OrderTimelineRepository
from app.services.crypto_payment_service import OXAPAY_EXTRA_KEY
from app.services.timeline_status_service import TimelineStatusRegistry


class OrderTimelineService:
    DEFAULT_LABELS: dict[str, str] = {
        "created": "Order created",
        "awaiting_payment": "Awaiting payment",
        "paid": "Payment confirmed",
        "processing": "Processing",
        "shipping": "Shipped",
        "delivered": "Delivered",
        "cancelled": "Order cancelled",
        "expired": "Order expired",
        "reopened": "Payment window reopened",
        "note": "Note",
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = OrderTimelineRepository(session)

    async def add_event(
        self,
        order: Order | int,
        *,
        status: str | None = None,
        note: str | None = None,
        actor: str | None = None,
        event_type: str = "status",
        meta: dict | None = None,
    ) -> OrderTimeline:
        order_id = order.id if isinstance(order, Order) else int(order)
        entry = await self._repo.add_event(
            order_id,
            event_type=event_type,
            status=status,
            note=note,
            actor=actor,
            meta=meta,
        )
        if status and isinstance(order, Order):
            self._update_order_snapshot(order, status, actor, entry.created_at)
            if status == "delivered":
                self._ensure_delivery_notice(order, actor, entry.created_at)
        return entry

    async def list_events(self, order: Order | int) -> list[OrderTimeline]:
        order_id = order.id if isinstance(order, Order) else int(order)
        return await self._repo.list_for_order(order_id)

    async def list_orders_with_status(
        self,
        status: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[Order]:
        return await self._repo.list_orders_with_latest_status(
            status,
            limit=limit,
            offset=offset,
        )

    @classmethod
    def label_for_status(cls, status: str | None) -> str:
        if not status:
            return "Update"
        custom_label = TimelineStatusRegistry.label(status)
        if custom_label:
            return custom_label
        return cls.DEFAULT_LABELS.get(status, status.replace("_", " ").title())

    @classmethod
    def _update_order_snapshot(
        cls,
        order: Order,
        status: str,
        actor: str | None,
        timestamp: datetime | None,
    ) -> None:
        label = cls.label_for_status(status)
        snapshot = {
            "status": status,
            "label": label,
            "actor": actor,
            "updated_at": (timestamp or datetime.now(tz=timezone.utc)).isoformat(),
        }
        extra = dict(order.extra_attrs or {})
        extra["timeline_status"] = snapshot
        order.extra_attrs = extra

    @staticmethod
    def _ensure_delivery_notice(
        order: Order,
        actor: str | None,
        timestamp: datetime | None,
    ) -> None:
        extra = dict(order.extra_attrs or {})
        meta = extra.get(OXAPAY_EXTRA_KEY)
        meta_dict = dict(meta) if isinstance(meta, dict) else {}
        delivery_record = meta_dict.get("delivery_notice")
        if isinstance(delivery_record, dict) and delivery_record.get("sent_at"):
            extra[OXAPAY_EXTRA_KEY] = meta_dict
            order.extra_attrs = extra
            return
        record = {
            "sent_at": (timestamp or datetime.now(tz=timezone.utc)).isoformat(),
            "sent_by": actor or "system",
        }
        meta_dict["delivery_notice"] = record
        extra[OXAPAY_EXTRA_KEY] = meta_dict
        order.extra_attrs = extra
