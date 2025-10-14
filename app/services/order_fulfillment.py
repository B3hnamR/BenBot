from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories.order import OrderRepository
from app.services.crypto_payment_service import OXAPAY_EXTRA_KEY


async def ensure_fulfillment(
    session: AsyncSession,
    bot: Bot,
    order: Order,
    *,
    source: str,
) -> bool:
    meta = _get_payment_meta(order)
    fulfillment = meta.get("fulfillment") or {}
    if fulfillment.get("delivered_at"):
        return False

    await _ensure_relationships_loaded(session, order)

    user = order.user
    if user is None or user.telegram_id is None:
        return False

    await bot.send_message(user.telegram_id, _build_user_message(order))

    settings = get_settings()
    admin_message = _build_admin_message(order, source)
    for admin_id in settings.owner_user_ids:
        await bot.send_message(admin_id, admin_message)

    fulfilled_at = datetime.now(tz=timezone.utc).isoformat()
    fulfillment.update({
        "delivered_at": fulfilled_at,
        "delivered_by": source,
    })
    meta.update({"fulfillment": fulfillment})

    await OrderRepository(session).merge_extra_attrs(order, {OXAPAY_EXTRA_KEY: meta})
    order.extra_attrs = order.extra_attrs or {}
    order.extra_attrs[OXAPAY_EXTRA_KEY] = meta
    return True


async def _ensure_relationships_loaded(session: AsyncSession, order: Order) -> None:
    if (order.user is None or order.user.telegram_id is None) or order.product is None:
        await session.refresh(order, attribute_names=["user", "product"])


def _get_payment_meta(order: Order) -> dict[str, Any]:
    extra = order.extra_attrs or {}
    meta = extra.get(OXAPAY_EXTRA_KEY)
    return dict(meta) if isinstance(meta, dict) else {}


def _build_user_message(order: Order) -> str:
    product_name = getattr(order.product, "name", "your purchase")
    lines = [
        "<b>Payment received!</b>",
        f"Order <code>{order.public_id}</code> for {product_name} is confirmed.",
        "We'll process fulfillment shortly and keep you posted.",
    ]
    return "\n".join(lines)


def _build_admin_message(order: Order, source: str) -> str:
    product_name = getattr(order.product, "name", "product")
    lines = [
        "<b>Order fulfilled</b>",
        f"Order: <code>{order.public_id}</code>",
        f"Product: {product_name}",
        f"User ID: {order.user_id}",
        f"Triggered by: {source}",
    ]
    return "\n".join(lines)

