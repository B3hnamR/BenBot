from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.core.enums import CouponStatus
from app.infrastructure.db.models import Coupon, CouponRedemption

from .base import BaseRepository


class CouponRepository(BaseRepository):
    async def get_by_code(self, code: str, *, with_relations: bool = True) -> Coupon | None:
        stmt: Select[tuple[Coupon]] = select(Coupon).where(Coupon.code == code)
        if with_relations:
            stmt = stmt.options(selectinload(Coupon.redemptions))
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def create_coupon(self, coupon: Coupon) -> Coupon:
        await self.add(coupon)
        return coupon

    async def list_active(self, now: datetime | None = None) -> list[Coupon]:
        stmt = select(Coupon).where(Coupon.status == CouponStatus.ACTIVE)
        if now is not None:
            stmt = stmt.where(
                (Coupon.start_at.is_(None) | (Coupon.start_at <= now)),
                (Coupon.end_at.is_(None) | (Coupon.end_at >= now)),
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def add_redemption(
        self,
        coupon: Coupon,
        *,
        user_id: int,
        order_id: int | None,
        amount_applied,
        meta: dict | None = None,
    ) -> CouponRedemption:
        redemption = CouponRedemption(
            coupon=coupon,
            user_id=user_id,
            order_id=order_id,
            amount_applied=amount_applied,
            meta=meta,
        )
        await self.add(redemption)
        return redemption

    async def count_redemptions(self, coupon_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(CouponRedemption).where(CouponRedemption.coupon_id == coupon_id)
        )
        return int(result.scalar_one())

    async def count_redemptions_for_user(self, coupon_id: int, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(CouponRedemption)
            .where(
                CouponRedemption.coupon_id == coupon_id,
                CouponRedemption.user_id == user_id,
            )
        )
        return int(result.scalar_one())
