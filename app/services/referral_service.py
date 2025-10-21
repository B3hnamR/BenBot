from __future__ import annotations

from uuid import uuid4
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LoyaltyTransactionType, ReferralRewardType
from app.infrastructure.db.models import LoyaltyTransaction, ReferralLink, ReferralReward
from app.infrastructure.db.repositories import LoyaltyRepository, ReferralRepository


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ReferralRepository(session)
        self._loyalty = LoyaltyRepository(session)

    async def create_link(
        self,
        *,
        owner_user_id: int,
        code: str | None = None,
        reward_type: ReferralRewardType,
        reward_value: Decimal,
        meta: dict | None = None,
    ) -> ReferralLink:
        link = ReferralLink(
            public_id=str(uuid4()),
            owner_user_id=owner_user_id,
            code=code or self._generate_code(),
            reward_type=reward_type,
            reward_value=reward_value,
            meta=meta,
        )
        await self._repo.create_link(link)
        await self._session.flush()
        return link

    async def record_click(self, link: ReferralLink) -> ReferralLink:
        await self._repo.increment_counters(link, clicks=1)
        await self._session.flush()
        return link

    async def record_signup(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int,
    ) -> ReferralLink:
        await self._repo.create_enrollment(
            link,
            referred_user_id=referred_user_id,
            status="signed_up",
        )
        await self._repo.increment_counters(link, signups=1)
        await self._session.flush()
        return link

    async def record_order(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int,
    ) -> ReferralLink:
        await self._repo.increment_counters(link, orders=1)
        await self._session.flush()
        return link

    async def reward_referral(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int,
        reward_type: ReferralRewardType | None = None,
        reward_value: Decimal | None = None,
        meta: dict | None = None,
    ) -> ReferralReward:
        reward_type = reward_type or link.reward_type
        reward_value = reward_value or link.reward_value

        loyalty_txn: LoyaltyTransaction | None = None
        if reward_type == ReferralRewardType.BONUS:
            account = await self._loyalty.get_account_by_user(link.owner_user_id)
            if account is None:
                account = await self._loyalty.create_account(link.owner_user_id)
            new_balance = account.balance + reward_value
            await self._loyalty.update_account_totals(
                account,
                balance=new_balance,
                earned_delta=reward_value,
            )
            loyalty_txn = await self._loyalty.add_transaction(
                account,
                transaction_type=LoyaltyTransactionType.EARN,
                amount=reward_value,
                balance_after=new_balance,
                reference=f"referral:{referred_user_id}",
                description="Referral reward",
                meta=meta,
            )

        reward = await self._repo.create_reward(
            link,
            referred_user_id=referred_user_id,
            reward_type=reward_type,
            reward_value=reward_value,
            loyalty_transaction_id=loyalty_txn.id if loyalty_txn else None,
            meta=meta,
        )
        await self._session.flush()
        return reward

    async def get_link_by_code(self, code: str) -> ReferralLink | None:
        return await self._repo.get_link_by_code(code)

    def _generate_code(self) -> str:
        return uuid4().hex[:10].upper()
