from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, delete, distinct, func, select
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

    async def get_by_id(self, coupon_id: int) -> Coupon | None:
        stmt = (
            select(Coupon)
            .options(selectinload(Coupon.redemptions))
            .where(Coupon.id == coupon_id)
        )
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()

    async def list_active(self, now: datetime | None = None) -> list[Coupon]:
        stmt = select(Coupon).where(Coupon.status == CouponStatus.ACTIVE)
        if now is not None:
            stmt = stmt.where(
                (Coupon.start_at.is_(None) | (Coupon.start_at <= now)),
                (Coupon.end_at.is_(None) | (Coupon.end_at >= now)),
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def list_recent(self, limit: int = 10) -> list[Coupon]:
        stmt = (
            select(Coupon)
            .options(selectinload(Coupon.redemptions))
            .order_by(Coupon.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def add_redemption(
        self,
        coupon: Coupon,
        *,
        user_id: int,
        order_id: int | None,
        amount_applied: Decimal,
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

    async def list_redemptions_for_order(self, order_id: int) -> list[CouponRedemption]:
        stmt = (
            select(CouponRedemption)
            .options(selectinload(CouponRedemption.coupon))
            .where(CouponRedemption.order_id == order_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def delete_redemptions_for_order(self, order_id: int) -> int:
        result = await self.session.execute(
            delete(CouponRedemption).where(CouponRedemption.order_id == order_id)
        )
        return int(result.rowcount or 0)

    async def list_recent_redemptions(self, coupon_id: int, limit: int = 5) -> list[CouponRedemption]:
        stmt = (
            select(CouponRedemption)
            .options(
                selectinload(CouponRedemption.user),
                selectinload(CouponRedemption.order),
            )
            .where(CouponRedemption.coupon_id == coupon_id)
            .order_by(CouponRedemption.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def count_unique_users(self, coupon_id: int) -> int:
        result = await self.session.execute(
            select(func.count(distinct(CouponRedemption.user_id))).where(
                CouponRedemption.coupon_id == coupon_id
            )
        )
        return int(result.scalar_one())

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

    async def delete_coupon(self, coupon: Coupon) -> None:
        await self.session.delete(coupon)
        await self.session.flush()
