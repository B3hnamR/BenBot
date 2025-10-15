from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories.order import OrderRepository
from app.services.crypto_payment_service import OXAPAY_EXTRA_KEY
from app.services.order_notification_service import OrderNotificationService


log = get_logger(__name__)


@dataclass(slots=True)
class InventoryUpdate:
    updated: bool
    before: int | None
    after: int | None
    product_deactivated: bool

    def as_meta(self) -> dict[str, Any]:
        return {
            "updated": self.updated,
            "before": self.before,
            "after": self.after,
            "product_deactivated": self.product_deactivated,
        }


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

    inventory_update = await _apply_inventory_adjustment(order)

    await bot.send_message(user.telegram_id, _build_user_message(order, inventory_update))

    notification_extra = _inventory_admin_lines(inventory_update)
    notifications = OrderNotificationService(session)
    await notifications.notify_payment(
        bot,
        order,
        source=source,
        extra_lines=notification_extra,
    )

    fulfilled_at = datetime.now(tz=timezone.utc).isoformat()
    fulfillment.update({
        "delivered_at": fulfilled_at,
        "delivered_by": source,
    })
    if inventory_update is not None:
        fulfillment["inventory"] = inventory_update.as_meta()
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


def _build_user_message(order: Order, inventory_update: InventoryUpdate | None) -> str:
    product_name = getattr(order.product, "name", "your purchase")
    lines = [
        "<b>Payment received!</b>",
        f"Order <code>{order.public_id}</code> for {product_name} is confirmed.",
        "We'll process fulfillment shortly and keep you posted.",
    ]
    if inventory_update and inventory_update.after is not None:
        if inventory_update.after > 0:
            lines.append(f"Remaining stock for this item: {inventory_update.after}.")
        elif inventory_update.product_deactivated:
            lines.append("That was the last available item. The listing will be hidden temporarily.")

    delivery_note = None
    product = order.product
    if product and isinstance(product.extra_attrs, dict):
        delivery_note = product.extra_attrs.get("delivery_note") or product.extra_attrs.get("delivery_message")
    if delivery_note:
        lines.append("")
        lines.append(str(delivery_note))
    return "\n".join(lines)


def _inventory_admin_lines(inventory_update: InventoryUpdate | None) -> list[str]:
    if inventory_update is None:
        return []
    lines: list[str] = []
    if inventory_update.before is not None:
        after_value = (
            inventory_update.after if inventory_update.after is not None else "unknown"
        )
        lines.append(f"Inventory: {inventory_update.before} -> {after_value}")
    if inventory_update.product_deactivated:
        lines.append("Product was deactivated because inventory reached zero.")
    return lines


async def _apply_inventory_adjustment(order: Order) -> InventoryUpdate | None:
    product = order.product
    if product is None or product.inventory is None:
        return None

    before = int(product.inventory)
    if before <= 0:
        product.inventory = 0
        product.is_active = False
        log.warning(
            "fulfillment_inventory_exhausted",
            order_id=order.id,
            product_id=getattr(product, "id", None),
        )
        return InventoryUpdate(
            updated=False,
            before=before,
            after=0,
            product_deactivated=True,
        )

    product.inventory = before - 1
    product_deactivated = False
    if product.inventory <= 0:
        product.inventory = 0
        product.is_active = False
        product_deactivated = True

    log.info(
        "fulfillment_inventory_updated",
        order_id=order.id,
        product_id=getattr(product, "id", None),
        before=before,
        after=product.inventory,
        deactivated=product_deactivated,
    )

    return InventoryUpdate(
        updated=True,
        before=before,
        after=int(product.inventory),
        product_deactivated=product_deactivated,
    )

