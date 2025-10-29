from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories.order import OrderRepository
from app.services.config_service import ConfigService
from app.services.loyalty_service import LoyaltyService

CURRENCY_QUANT = Decimal("0.01")


def _loyalty_meta(order: Order) -> dict[str, Any]:
    extra = order.extra_attrs or {}
    meta = extra.get("loyalty")
    return dict(meta) if isinstance(meta, dict) else {}


async def ensure_points_available(
    session: AsyncSession,
    user_id: int,
    *,
    points: int,
) -> bool:
    if points <= 0:
        return True
    loyalty = LoyaltyService(session)
    return await loyalty.can_redeem_points(user_id, Decimal(points))


async def reserve_loyalty_for_order(
    session: AsyncSession,
    order: Order,
    user_id: int,
    *,
    points: int,
    value: Decimal,
    ratio: Decimal,
    currency: str,
) -> dict[str, Any]:
    if points <= 0 or value <= Decimal("0"):
        return _loyalty_meta(order)

    loyalty = LoyaltyService(session)
    transaction = await loyalty.reserve_points(
        user_id,
        points=Decimal(points),
        order_public_id=order.public_id,
        value=value,
        currency=currency,
    )

    meta = _loyalty_meta(order)
    redeem = meta.setdefault("redeem", {})
    redeem.update(
        {
            "points": points,
            "value": str(value.quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)),
            "ratio": str(ratio),
            "currency": currency,
            "transaction_id": transaction.id,
            "status": "reserved",
        }
    )
    await OrderRepository(session).merge_extra_attrs(order, {"loyalty": meta})
    order.extra_attrs = order.extra_attrs or {}
    order.extra_attrs["loyalty"] = meta
    return meta


async def finalize_loyalty_on_paid(session: AsyncSession, order: Order) -> dict[str, Any]:
    meta = _loyalty_meta(order)
    loyalty = LoyaltyService(session)
    updated = False

    redeem = meta.get("redeem")
    if isinstance(redeem, dict):
        txn_id = redeem.get("transaction_id")
        status = redeem.get("status")
        if txn_id and status in {"reserved", "pending"}:
            transaction = await loyalty.finalize_reservation(txn_id, status="applied")
            if transaction is not None:
                redeem["status"] = "applied"
                updated = True

    config_service = ConfigService(session)
    settings = await config_service.get_loyalty_settings()
    if settings.auto_earn and settings.points_per_currency > 0 and order.user_id:
        earn_points = (
            Decimal(order.total_amount or Decimal("0"))
            * Decimal(str(settings.points_per_currency))
        ).quantize(CURRENCY_QUANT, rounding=ROUND_HALF_UP)
        if earn_points > Decimal("0"):
            transaction = await loyalty.earn_points(
                order.user_id,
                amount=earn_points,
                reference=order.public_id,
                description="Order loyalty reward",
                meta={
                    "order_public_id": order.public_id,
                    "status": "awarded",
                },
            )
            meta["earn"] = {
                "points": str(earn_points),
                "transaction_id": transaction.id,
                "status": "awarded",
            }
            updated = True

    if updated:
        await OrderRepository(session).merge_extra_attrs(order, {"loyalty": meta})
        order.extra_attrs = order.extra_attrs or {}
        order.extra_attrs["loyalty"] = meta
    return meta


async def refund_loyalty_for_order(
    session: AsyncSession,
    order: Order,
    *,
    reason: str,
) -> dict[str, Any]:
    meta = _loyalty_meta(order)
    redeem = meta.get("redeem")
    if not isinstance(redeem, dict):
        return meta
    status = redeem.get("status")
    if status == "refunded":
        return meta

    points = Decimal(str(redeem.get("points") or "0"))
    if points <= Decimal("0") or not order.user_id:
        return meta

    loyalty = LoyaltyService(session)
    transaction = await loyalty.restore_points(
        order.user_id,
        points=points,
        order_public_id=order.public_id,
        reason=reason,
    )
    redeem["status"] = "refunded"
    redeem["refund_transaction_id"] = transaction.id
    redeem["refund_reason"] = reason

    await OrderRepository(session).merge_extra_attrs(order, {"loyalty": meta})
    order.extra_attrs = order.extra_attrs or {}
    order.extra_attrs["loyalty"] = meta
    return meta
