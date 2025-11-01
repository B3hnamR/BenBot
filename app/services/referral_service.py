from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from decimal import Decimal
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LoyaltyTransactionType, ReferralRewardType
from app.infrastructure.db.models import (
    LoyaltyTransaction,
    ReferralEnrollment,
    ReferralLink,
    ReferralReward,
)
from app.infrastructure.db.repositories import LoyaltyRepository, ReferralRepository


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ReferralRepository(session)
        self._loyalty = LoyaltyRepository(session)

    async def get_link_by_id(self, link_id: int) -> ReferralLink | None:
        return await self._repo.get_link_by_id(link_id)

    async def get_link_by_code(self, code: str) -> ReferralLink | None:
        return await self._repo.get_link_by_code(code)

    async def list_links_for_owner(self, owner_user_id: int, *, limit: int = 10) -> list[ReferralLink]:
        return await self._repo.list_links_for_owner(owner_user_id, limit=limit)

    async def list_recent_links(self, *, limit: int = 20) -> list[ReferralLink]:
        return await self._repo.list_recent_links(limit=limit)

    async def create_link(
        self,
        *,
        owner_user_id: int,
        reward_type: ReferralRewardType,
        reward_value: Decimal,
        code: str | None = None,
        label: str | None = None,
        meta: dict | None = None,
    ) -> ReferralLink:
        payload_meta = dict(meta or {})
        if label:
            payload_meta["label"] = label
        link = ReferralLink(
            public_id=str(uuid4()),
            owner_user_id=owner_user_id,
            code=code or self._generate_code(),
            reward_type=reward_type,
            reward_value=reward_value,
            meta=payload_meta if payload_meta else None,
        )
        await self._repo.create_link(link)
        await self._session.flush()
        return link

    async def update_link(
        self,
        link: ReferralLink,
        *,
        reward_type: ReferralRewardType | None = None,
        reward_value: Decimal | None = None,
        label: str | None = None,
        meta_updates: dict | None = None,
    ) -> ReferralLink:
        if reward_type is not None:
            link.reward_type = reward_type
        if reward_value is not None:
            link.reward_value = reward_value
        meta = dict(link.meta or {})
        if label is not None:
            if label:
                meta["label"] = label
            else:
                meta.pop("label", None)
        if meta_updates:
            meta.update(meta_updates)
        link.meta = meta or None
        await self._session.flush()
        return link

    async def delete_link(self, link: ReferralLink) -> None:
        await self._repo.delete_link(link)

    async def list_enrollments_for_link(self, link_id: int, *, limit: int = 20) -> list[ReferralEnrollment]:
        return await self._repo.list_enrollments_for_link(link_id, limit=limit)

    async def list_rewards_for_link(self, link_id: int, *, limit: int = 20) -> list[ReferralReward]:
        return await self._repo.list_rewards_for_link(link_id, limit=limit)

    async def list_pending_commission_rewards(self, *, limit: int = 20) -> list[ReferralReward]:
        return await self._repo.list_pending_commission_rewards(limit=limit)

    async def get_enrollment_by_user(self, referred_user_id: int) -> ReferralEnrollment | None:
        return await self._repo.get_enrollment_by_user(referred_user_id)

    async def ensure_enrollment(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int | None,
        status: str = "pending",
        referral_code: str | None = None,
        meta: dict | None = None,
    ) -> Tuple[ReferralEnrollment, bool]:
        created = False
        enrollment = None
        if referred_user_id is not None:
            enrollment = await self._repo.get_enrollment_by_user(referred_user_id)
            if enrollment and enrollment.link_id != link.id:
                # Respect the first associated link; do not overwrite with another link.
                return enrollment, False

        if enrollment is None:
            enrollment = await self._repo.create_enrollment(
                link,
                referred_user_id=referred_user_id,
                status=status,
                referral_code=referral_code,
                meta=meta,
            )
            created = True
        else:
            if status and enrollment.status != status:
                enrollment.status = status
            if referral_code:
                enrollment.referral_code = referral_code
            if meta:
                existing_meta = dict(enrollment.meta or {})
                existing_meta.update(meta)
                enrollment.meta = existing_meta
        await self._session.flush()
        return enrollment, created

    async def record_click(self, link: ReferralLink) -> ReferralLink:
        await self._repo.increment_counters(link, clicks=1)
        await self._session.flush()
        return link

    async def record_signup(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int,
    ) -> ReferralEnrollment:
        enrollment, created = await self.ensure_enrollment(
            link,
            referred_user_id=referred_user_id,
            status="signed_up",
        )
        if created:
            await self._repo.increment_counters(link, signups=1)
        await self._session.flush()
        return enrollment

    async def record_order(
        self,
        link: ReferralLink,
        *,
        referred_user_id: int,
    ) -> ReferralEnrollment:
        enrollment, _ = await self.ensure_enrollment(
            link,
            referred_user_id=referred_user_id,
            status="ordered",
        )
        await self._repo.increment_counters(link, orders=1)
        await self._session.flush()
        return enrollment

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
        reward_value = reward_value if reward_value is not None else link.reward_value

        loyalty_txn: LoyaltyTransaction | None = None
        meta_payload = dict(meta or {})

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
                meta=meta_payload or None,
            )

        reward = await self._repo.create_reward(
            link,
            referred_user_id=referred_user_id,
            reward_type=reward_type,
            reward_value=reward_value,
            loyalty_transaction_id=loyalty_txn.id if loyalty_txn else None,
            meta=meta_payload or None,
        )
        if reward_type == ReferralRewardType.BONUS:
            reward.rewarded_at = datetime.now(tz=timezone.utc)
        await self._session.flush()
        return reward

    async def mark_reward_paid(self, reward: ReferralReward) -> ReferralReward:
        return await self._repo.mark_reward_paid(reward)

    async def get_reward_by_id(self, reward_id: int) -> ReferralReward | None:
        return await self._repo.get_reward_by_id(reward_id)

    async def count_rewards_for_user(self, link_id: int, referred_user_id: int) -> int:
        return await self._repo.count_rewards_for_user(link_id, referred_user_id)

    def _generate_code(self) -> str:
        return uuid4().hex[:10].upper()
