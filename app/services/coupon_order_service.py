from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories import OrderRepository
from app.infrastructure.db.repositories.coupon import CouponRepository


def _coupon_meta(order: Order) -> dict[str, Any]:
    extra = order.extra_attrs or {}
    meta = extra.get("coupon")
    return dict(meta) if isinstance(meta, dict) else {}


async def finalize_coupon_on_paid(session: AsyncSession, order: Order) -> dict[str, Any]:
    meta = _coupon_meta(order)
    if order.id is None:
        return meta

    repo = CouponRepository(session)
    redemptions = await repo.list_redemptions_for_order(order.id)
    if not redemptions and not meta:
        return meta

    updated = False
    timestamp = datetime.now(tz=timezone.utc).isoformat()

    for redemption in redemptions:
        redemption.meta = redemption.meta or {}
        status = (redemption.meta.get("status") or "").lower()
        if status != "applied":
            redemption.meta["status"] = "applied"
            redemption.meta["updated_at"] = timestamp
            updated = True

    status = (meta.get("status") or "").lower()
    if meta and status in {"pending", "reserved"}:
        meta["status"] = "applied"
        meta["applied_at"] = timestamp
        updated = True

    if updated:
        await OrderRepository(session).merge_extra_attrs(order, {"coupon": meta})
        order.extra_attrs = order.extra_attrs or {}
        order.extra_attrs["coupon"] = meta

    return meta


async def release_coupon_for_order(
    session: AsyncSession,
    order: Order,
    *,
    reason: str,
) -> dict[str, Any]:
    meta = _coupon_meta(order)
    if order.id is None:
        return meta

    repo = CouponRepository(session)
    redemptions = await repo.list_redemptions_for_order(order.id)
    if redemptions:
        await repo.delete_redemptions_for_order(order.id)

    status = (meta.get("status") or "").lower() if meta else ""
    if meta and status not in {"failed", "refunded"}:
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        meta["status"] = "refunded"
        meta["refund_reason"] = reason
        meta["refunded_at"] = timestamp
        await OrderRepository(session).merge_extra_attrs(order, {"coupon": meta})
        order.extra_attrs = order.extra_attrs or {}
        order.extra_attrs["coupon"] = meta

    return meta
