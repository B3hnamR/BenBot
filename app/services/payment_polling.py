from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Optional

from aiogram import Bot

from app.bot.factory import create_bot
from app.core.config import get_settings
from app.core.enums import OrderStatus
from app.core.logging import configure_logging, get_logger
from app.infrastructure.db.repositories.order import OrderRepository
from app.infrastructure.db.session import init_engine, session_factory
from app.services.crypto_payment_service import CryptoPaymentService
from app.services.order_fulfillment import ensure_fulfillment
from app.services.order_notification_service import OrderNotificationService
from app.services.order_service import OrderService
from app.services.loyalty_order_service import refund_loyalty_for_order

log = get_logger(__name__)


async def poll_pending_orders(bot: Bot, *, batch_size: int = 25) -> int:
    async with session_factory() as session:
        repo = OrderRepository(session)
        orders = await repo.list_pending_crypto(limit=batch_size)
        if not orders:
            await session.commit()
            return 0

        crypto_service = CryptoPaymentService(session)
        order_service = OrderService(session)
        notifications = OrderNotificationService(session)
        updated = 0

        for order in orders:
            previous_status = order.status
            try:
                result = await crypto_service.refresh_order_status(order)
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "poll_refresh_failed",
                    order_id=order.id,
                    public_id=order.public_id,
                    error=str(exc),
                )
                continue

            if result.updated:
                updated += 1
                if order.status == OrderStatus.PAID:
                    await ensure_fulfillment(session, bot, order, source="poller")
                elif order.status == OrderStatus.CANCELLED:
                    await notifications.notify_cancelled(bot, order, reason="provider_update")
                    await refund_loyalty_for_order(session, order, reason="provider_update")
                elif order.status == OrderStatus.EXPIRED:
                    await notifications.notify_expired(bot, order, reason="provider_update")
                    await refund_loyalty_for_order(session, order, reason="provider_update")

            previous_status = order.status
            await order_service.enforce_expiration(order)
            if order.status == OrderStatus.EXPIRED and previous_status != OrderStatus.EXPIRED:
                await notifications.notify_expired(bot, order, reason="timeout_check")
                await refund_loyalty_for_order(session, order, reason="timeout_check")

        await session.commit()
        return updated


async def run(interval_seconds: int = 60, *, batch_size: int = 25) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await init_engine()

    bot: Optional[Bot] = None
    try:
        bot = create_bot(settings)
        log.info("payment_polling_started", interval_seconds=interval_seconds)
        while True:
            try:
                updated = await poll_pending_orders(bot, batch_size=batch_size)
                if updated:
                    log.info("payment_polling_cycle", updated=updated)
            except Exception as exc:  # noqa: BLE001
                log.exception("payment_polling_error", error=str(exc))
            await asyncio.sleep(interval_seconds)
    finally:
        if bot is not None:
            with suppress(Exception):
                await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
