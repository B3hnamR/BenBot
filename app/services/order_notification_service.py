from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories import OrderRepository
from app.services.config_service import ConfigService

NOTIFICATION_META_KEY = "notifications"


class OrderNotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orders = OrderRepository(session)
        self._config_service = ConfigService(session)
        self._log = get_logger(__name__)

    async def notify_payment(
        self,
        bot: Bot,
        order: Order,
        *,
        source: str,
        extra_lines: Iterable[str] | None = None,
    ) -> bool:
        settings = await self._config_service.get_alert_settings()
        if not settings.notify_payment:
            return False

        meta = self._notification_meta(order)
        if meta.get("payment_sent"):
            return False

        message_lines = [
            "<b>Order paid</b>",
            f"Order: <code>{order.public_id}</code>",
            f"Product: {getattr(order.product, 'name', 'product')}",
            f"Amount: {order.total_amount} {order.currency}",
            f"User ID: {order.user_id}",
            f"Source: {source}",
        ]
        appended = list(extra_lines or [])
        if appended:
            message_lines.append("")
            message_lines.extend(appended)

        await self._dispatch(bot, "\n".join(message_lines))

        meta["payment_sent"] = {
            "sent_at": self._timestamp(),
            "source": source,
        }
        await self._persist_meta(order, meta)
        self._log.info(
            "order_alert_payment",
            order_id=order.id,
            source=source,
        )
        return True

    async def notify_cancelled(
        self,
        bot: Bot,
        order: Order,
        *,
        reason: str,
    ) -> bool:
        settings = await self._config_service.get_alert_settings()
        if not settings.notify_cancellation:
            return False

        meta = self._notification_meta(order)
        if meta.get("cancel_sent"):
            return False

        message_lines = [
            "<b>Order cancelled</b>",
            f"Order: <code>{order.public_id}</code>",
            f"Amount: {order.total_amount} {order.currency}",
            f"User ID: {order.user_id}",
            f"Reason: {reason}",
        ]
        await self._dispatch(bot, "\n".join(message_lines))

        meta["cancel_sent"] = {
            "sent_at": self._timestamp(),
            "reason": reason,
        }
        await self._persist_meta(order, meta)
        self._log.info(
            "order_alert_cancelled",
            order_id=order.id,
            reason=reason,
        )
        return True

    async def notify_expired(
        self,
        bot: Bot,
        order: Order,
        *,
        reason: str,
    ) -> bool:
        settings = await self._config_service.get_alert_settings()
        if not settings.notify_expiration:
            return False

        meta = self._notification_meta(order)
        if meta.get("expired_sent"):
            return False

        message_lines = [
            "<b>Order expired</b>",
            f"Order: <code>{order.public_id}</code>",
            f"Amount: {order.total_amount} {order.currency}",
            f"User ID: {order.user_id}",
            f"Reason: {reason}",
        ]
        await self._dispatch(bot, "\n".join(message_lines))

        meta["expired_sent"] = {
            "sent_at": self._timestamp(),
            "reason": reason,
        }
        await self._persist_meta(order, meta)
        self._log.info(
            "order_alert_expired",
            order_id=order.id,
            reason=reason,
        )
        return True

    async def _dispatch(self, bot: Bot, text: str) -> None:
        recipients = self._admin_ids()
        if not recipients:
            return
        for admin_id in recipients:
            try:
                await bot.send_message(admin_id, text)
            except Exception as exc:  # noqa: BLE001
                self._log.warning(
                    "order_alert_delivery_failed",
                    admin_id=admin_id,
                    error=str(exc),
                )

    def _notification_meta(self, order: Order) -> dict[str, Any]:
        extra = order.extra_attrs or {}
        data = extra.get(NOTIFICATION_META_KEY)
        return dict(data) if isinstance(data, dict) else {}

    async def _persist_meta(self, order: Order, meta: dict[str, Any]) -> None:
        await self._orders.merge_extra_attrs(order, {NOTIFICATION_META_KEY: meta})
        extra = dict(order.extra_attrs or {})
        extra[NOTIFICATION_META_KEY] = meta
        order.extra_attrs = extra

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    @staticmethod
    def _admin_ids() -> list[int]:
        settings = get_settings()
        return list(settings.owner_user_ids or [])
