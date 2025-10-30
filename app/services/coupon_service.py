from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import CouponStatus, CouponType
from app.infrastructure.db.models import Coupon
from app.infrastructure.db.repositories import CouponRepository


class CouponService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CouponRepository(session)

    async def create_coupon(self, coupon: Coupon) -> Coupon:
        await self._repo.create_coupon(coupon)
        await self._session.flush()
        return coupon

    async def get_coupon(self, code: str) -> Coupon | None:
        return await self._repo.get_by_code(code)

    def calculate_discount(self, coupon: Coupon, order_total: Decimal) -> Decimal:
        return self._calculate_discount(coupon, order_total)

    async def validate_coupon(
        self,
        coupon: Coupon,
        *,
        user_id: int,
        order_total: Decimal,
        now: datetime | None = None,
    ) -> None:
        if coupon.status != CouponStatus.ACTIVE:
            raise ValueError("Coupon is not active.")
        if now is None:
            now = datetime.now(tz=timezone.utc)
        if coupon.start_at and coupon.start_at > now:
            raise ValueError("Coupon is not yet active.")
        if coupon.end_at and coupon.end_at < now:
            raise ValueError("Coupon has expired.")
        if coupon.min_order_total and order_total < coupon.min_order_total:
            raise ValueError("Order total does not meet coupon minimum.")
        if coupon.max_redemptions is not None:
            total_used = await self._repo.count_redemptions(coupon.id)
            if total_used >= coupon.max_redemptions:
                raise ValueError("Coupon usage limit reached.")
        if coupon.per_user_limit is not None:
            user_used = await self._repo.count_redemptions_for_user(coupon.id, user_id)
            if user_used >= coupon.per_user_limit:
                raise ValueError("You have already used this coupon the maximum number of times.")

    async def apply_coupon(
        self,
        coupon: Coupon,
        *,
        user_id: int,
        order_id: int | None,
        order_total: Decimal,
    ) -> Decimal:
        await self.validate_coupon(coupon, user_id=user_id, order_total=order_total)
        discount = self.calculate_discount(coupon, order_total)
        await self._repo.add_redemption(
            coupon,
            user_id=user_id,
            order_id=order_id,
            amount_applied=discount,
            meta={
                "status": "reserved",
                "order_total": str(order_total),
            },
        )
        await self._session.flush()
        return discount

    async def deactivate_coupon(self, coupon: Coupon) -> Coupon:
        coupon.status = CouponStatus.INACTIVE
        await self._session.flush()
        return coupon

    def _calculate_discount(self, coupon: Coupon, order_total: Decimal) -> Decimal:
        if coupon.coupon_type == CouponType.FIXED:
            value = coupon.amount or Decimal("0")
        elif coupon.coupon_type == CouponType.PERCENT:
            percentage = coupon.percentage or Decimal("0")
            value = (order_total * (percentage / Decimal("100")))
        elif coupon.coupon_type == CouponType.SHIPPING:
            value = coupon.amount or Decimal("0")
        else:
            value = Decimal("0")

        if coupon.max_discount_amount is not None:
            value = min(value, coupon.max_discount_amount)
        return max(Decimal("0"), value)
