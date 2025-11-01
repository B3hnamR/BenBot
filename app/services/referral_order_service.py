from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ReferralRewardType
from app.infrastructure.db.models import Order
from app.infrastructure.db.repositories import OrderRepository
from app.services.config_service import ConfigService
from app.services.referral_service import ReferralService


async def attach_referral_to_order(
    session: AsyncSession,
    order: Order,
    *,
    user_id: int,
) -> dict | None:
    config_service = ConfigService(session)
    referral_settings = await config_service.get_referral_settings()
    if not referral_settings.enabled:
        return None

    referral_service = ReferralService(session)
    enrollment = await referral_service.get_enrollment_by_user(user_id)
    if enrollment is None or enrollment.link is None:
        return None

    link = enrollment.link
    if link.owner_user_id == user_id:
        return None

    reward_type = link.reward_type
    reward_value = link.reward_value

    referral_meta = {
        "link_id": link.id,
        "link_code": link.code,
        "owner_user_id": link.owner_user_id,
        "reward_type": reward_type.value,
        "reward_value": str(reward_value),
        "status": "pending",
        "auto_reward": referral_settings.auto_reward,
        "recorded_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    if enrollment.id:
        referral_meta["enrollment_id"] = enrollment.id
    if link.meta and "label" in link.meta:
        referral_meta["label"] = link.meta["label"]

    await OrderRepository(session).merge_extra_attrs(order, {"referral": referral_meta})
    return referral_meta


async def finalize_referral_on_paid(session: AsyncSession, order: Order) -> dict | None:
    config_service = ConfigService(session)
    referral_settings = await config_service.get_referral_settings()
    if not referral_settings.enabled:
        return None

    referral_service = ReferralService(session)
    referral_meta = _get_referral_meta(order)
    if referral_meta is None:
        if order.user_id is None:
            return None
        referral_meta = await attach_referral_to_order(
            session,
            order,
            user_id=order.user_id,
        )
        if referral_meta is None:
            return None

    if referral_meta.get("status") in {"applied", "cancelled", "pending_commission"}:
        return referral_meta

    link_id = referral_meta.get("link_id")
    if not link_id:
        return referral_meta
    link = await referral_service.get_link_by_id(int(link_id))
    if link is None:
        referral_meta["status"] = "invalid_link"
        await OrderRepository(session).merge_extra_attrs(order, {"referral": referral_meta})
        return referral_meta

    if order.user_id is None or order.user_id == link.owner_user_id:
        referral_meta["status"] = "ignored"
        await OrderRepository(session).merge_extra_attrs(order, {"referral": referral_meta})
        return referral_meta

    if order.user_id is not None:
        await referral_service.record_order(
            link,
            referred_user_id=order.user_id,
        )

    reward_type = ReferralRewardType(referral_meta.get("reward_type", link.reward_type.value))
    reward_value_raw = referral_meta.get("reward_value")
    try:
        reward_value = Decimal(str(reward_value_raw))
    except Exception:  # noqa: BLE001
        reward_value = link.reward_value

    reward_amount = reward_value
    reward_meta: dict[str, str] = {
        "order_id": str(order.id),
        "order_public_id": order.public_id,
        "order_total": str(order.total_amount or Decimal("0")),
        "order_currency": order.currency,
    }

    if reward_type == ReferralRewardType.COMMISSION:
        order_total = Decimal(str(order.total_amount or "0"))
        if order_total <= Decimal("0"):
            referral_meta["status"] = "no_total"
            await OrderRepository(session).merge_extra_attrs(order, {"referral": referral_meta})
            return referral_meta
        # Interpret reward value as percentage by default.
        reward_amount = (order_total * reward_value / Decimal("100")).quantize(Decimal("0.01"))
        reward_meta["commission_rate"] = str(reward_value)
        reward_meta["calculated_amount"] = str(reward_amount)

    reward = await referral_service.reward_referral(
        link,
        referred_user_id=order.user_id,
        reward_type=reward_type,
        reward_value=reward_amount,
        meta=reward_meta,
    )

    if reward_type == ReferralRewardType.BONUS:
        referral_meta["status"] = "applied"
        referral_meta["rewarded_at"] = reward.rewarded_at.isoformat() if reward.rewarded_at else None
    else:
        referral_meta["status"] = "pending_commission"
        referral_meta["rewarded_at"] = reward.rewarded_at.isoformat() if reward.rewarded_at else None
    referral_meta["reward_id"] = reward.id
    referral_meta["reward_value_actual"] = str(reward.reward_value)

    await OrderRepository(session).merge_extra_attrs(order, {"referral": referral_meta})
    return referral_meta


async def cancel_referral_for_order(session: AsyncSession, order: Order, *, reason: str) -> None:
    referral_meta = _get_referral_meta(order)
    if referral_meta is None:
        return
    status = referral_meta.get("status")
    if status in {"applied", "refunded", "cancelled"}:
        return
    referral_meta["status"] = "cancelled"
    referral_meta["cancel_reason"] = reason
    await OrderRepository(session).merge_extra_attrs(order, {"referral": referral_meta})


def _get_referral_meta(order: Order) -> dict | None:
    extra = order.extra_attrs or {}
    referral = extra.get("referral")
    if isinstance(referral, dict):
        return dict(referral)
    return None
