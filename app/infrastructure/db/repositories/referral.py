from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.enums import ReferralRewardType
from app.infrastructure.db.models import ReferralEnrollment, ReferralLink, ReferralReward

from .base import BaseRepository


class ReferralRepository(BaseRepository):
    async def get_link_by_id(self, link_id: int) -> ReferralLink | None:
        result = await self.session.execute(
            select(ReferralLink)
            .options(selectinload(ReferralLink.enrollments), selectinload(ReferralLink.rewards))
            .where(ReferralLink.id == link_id)
        )
        return result.unique().scalar_one_or_none()

    async def get_link_by_code(self, code: str) -> ReferralLink | None:
        result = await self.session.execute(
            select(ReferralLink)
            .options(selectinload(ReferralLink.enrollments), selectinload(ReferralLink.rewards))
            .where(ReferralLink.code == code)
        )
        return result.unique().scalar_one_or_none()

    async def create_link(self, link: ReferralLink) -> ReferralLink:
        await self.add(link)
        return link

    async def delete_link(self, link: ReferralLink) -> None:
        await self.session.delete(link)

    async def list_links_for_owner(self, owner_user_id: int, *, limit: int = 10) -> list[ReferralLink]:
        result = await self.session.execute(
            select(ReferralLink)
            .options(selectinload(ReferralLink.enrollments), selectinload(ReferralLink.rewards))
            .where(ReferralLink.owner_user_id == owner_user_id)
            .order_by(ReferralLink.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def list_recent_links(self, *, limit: int = 20) -> list[ReferralLink]:
        result = await self.session.execute(
            select(ReferralLink)
            .options(selectinload(ReferralLink.enrollments), selectinload(ReferralLink.rewards))
            .order_by(ReferralLink.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def create_enrollment(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int | None = None,
        status: str = "pending",
        referral_code: str | None = None,
        meta: dict | None = None,
    ) -> ReferralEnrollment:
        enrollment = ReferralEnrollment(
            link=link,
            referred_user_id=referred_user_id,
            status=status,
            referral_code=referral_code,
            meta=meta,
        )
        await self.add(enrollment)
        return enrollment

    async def get_enrollment_by_user(self, referred_user_id: int) -> ReferralEnrollment | None:
        result = await self.session.execute(
            select(ReferralEnrollment)
            .options(selectinload(ReferralEnrollment.link))
            .where(ReferralEnrollment.referred_user_id == referred_user_id)
            .order_by(ReferralEnrollment.created_at.desc())
        )
        return result.scalars().first()

    async def list_enrollments_for_link(self, link_id: int, *, limit: int = 20) -> list[ReferralEnrollment]:
        result = await self.session.execute(
            select(ReferralEnrollment)
            .options(selectinload(ReferralEnrollment.referred_user))
            .where(ReferralEnrollment.link_id == link_id)
            .order_by(ReferralEnrollment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def create_reward(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int | None,
        reward_type,
        reward_value,
        loyalty_transaction_id: int | None,
        meta: dict | None = None,
    ) -> ReferralReward:
        reward = ReferralReward(
            link=link,
            referred_user_id=referred_user_id,
            reward_type=reward_type,
            reward_value=reward_value,
            loyalty_transaction_id=loyalty_transaction_id,
            meta=meta,
        )
        await self.add(reward)
        return reward

    async def list_rewards_for_link(self, link_id: int, *, limit: int = 20) -> list[ReferralReward]:
        result = await self.session.execute(
            select(ReferralReward)
            .options(selectinload(ReferralReward.referred_user))
            .where(ReferralReward.link_id == link_id)
            .order_by(ReferralReward.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def increment_counters(
        self,
        link: ReferralLink,
        *,
        clicks: int = 0,
        signups: int = 0,
        orders: int = 0,
    ) -> ReferralLink:
        link.total_clicks += clicks
        link.total_signups += signups
        link.total_orders += orders
        return link

    async def count_rewards_for_user(self, link_id: int, referred_user_id: int) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(ReferralReward)
            .where(
                ReferralReward.link_id == link_id,
                ReferralReward.referred_user_id == referred_user_id,
            )
        )
        return int(result.scalar_one())

    async def mark_reward_paid(self, reward: ReferralReward) -> ReferralReward:
        reward.rewarded_at = datetime.now(tz=timezone.utc)
        await self.session.flush()
        return reward

    async def get_reward_by_id(self, reward_id: int) -> ReferralReward | None:
        result = await self.session.execute(
            select(ReferralReward)
            .options(selectinload(ReferralReward.link), selectinload(ReferralReward.referred_user))
            .where(ReferralReward.id == reward_id)
        )
        return result.unique().scalar_one_or_none()

    async def list_pending_commission_rewards(self, limit: int = 20) -> list[ReferralReward]:
        result = await self.session.execute(
            select(ReferralReward)
            .options(selectinload(ReferralReward.link), selectinload(ReferralReward.referred_user))
            .where(
                ReferralReward.reward_type == ReferralRewardType.COMMISSION,
                ReferralReward.rewarded_at.is_(None),
            )
            .order_by(ReferralReward.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())
