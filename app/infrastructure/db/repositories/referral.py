from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.infrastructure.db.models import ReferralEnrollment, ReferralLink, ReferralReward

from .base import BaseRepository


class ReferralRepository(BaseRepository):
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
