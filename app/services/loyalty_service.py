from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LoyaltyTransactionType
from app.infrastructure.db.models import LoyaltyAccount, LoyaltyTransaction
from app.infrastructure.db.repositories import LoyaltyRepository


class LoyaltyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._accounts = LoyaltyRepository(session)

    async def get_or_create_account(self, user_id: int) -> LoyaltyAccount:
        account = await self._accounts.get_account_by_user(user_id)
        if account is None:
            account = await self._accounts.create_account(user_id)
            await self._session.flush()
        return account

    async def adjust_balance(
        self,
        user_id: int,
        *,
        amount: Decimal,
        transaction_type: LoyaltyTransactionType,
        reference: str | None = None,
        description: str | None = None,
        meta: dict | None = None,
    ) -> LoyaltyTransaction:
        account = await self.get_or_create_account(user_id)
        new_balance = account.balance + amount
        if new_balance < Decimal("0"):
            raise ValueError("Insufficient loyalty balance.")

        earned_delta = amount if transaction_type == LoyaltyTransactionType.EARN else Decimal("0")
        redeemed_delta = (-amount) if transaction_type == LoyaltyTransactionType.REDEEM else Decimal("0")

        await self._accounts.update_account_totals(
            account,
            balance=new_balance,
            earned_delta=earned_delta,
            redeemed_delta=redeemed_delta,
        )
        txn = await self._accounts.add_transaction(
            account,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=new_balance,
            reference=reference,
            description=description,
            meta=meta,
        )
        await self._session.flush()
        return txn

    async def earn_points(
        self,
        user_id: int,
        *,
        amount: Decimal,
        reference: str | None = None,
        description: str | None = None,
        meta: dict | None = None,
    ) -> LoyaltyTransaction:
        if amount <= Decimal("0"):
            raise ValueError("Earn amount must be positive.")
        return await self.adjust_balance(
            user_id,
            amount=amount,
            transaction_type=LoyaltyTransactionType.EARN,
            reference=reference,
            description=description,
            meta=meta,
        )

    async def redeem_points(
        self,
        user_id: int,
        *,
        amount: Decimal,
        reference: str | None = None,
        description: str | None = None,
        meta: dict | None = None,
    ) -> LoyaltyTransaction:
        if amount <= Decimal("0"):
            raise ValueError("Redeem amount must be positive.")
        return await self.adjust_balance(
            user_id,
            amount=-amount,
            transaction_type=LoyaltyTransactionType.REDEEM,
            reference=reference,
            description=description,
            meta=meta,
        )

    async def get_balance(self, user_id: int) -> Decimal:
        account = await self._accounts.get_account_by_user(user_id)
        if account is None:
            return Decimal("0")
        return account.balance

    async def can_redeem_points(self, user_id: int, points: Decimal) -> bool:
        if points <= Decimal("0"):
            return True
        balance = await self.get_balance(user_id)
        return balance >= points

    async def reserve_points(
        self,
        user_id: int,
        *,
        points: Decimal,
        order_public_id: str,
        value: Decimal | None = None,
        currency: str | None = None,
    ) -> LoyaltyTransaction:
        if points <= Decimal("0"):
            raise ValueError("Points to reserve must be positive.")
        meta = {
            "order_public_id": order_public_id,
            "status": "reserved",
        }
        if value is not None:
            meta["value"] = str(value)
        if currency:
            meta["currency"] = currency
        return await self.redeem_points(
            user_id,
            amount=points,
            reference=order_public_id,
            description="Order loyalty redemption",
            meta=meta,
        )

    async def finalize_reservation(
        self,
        transaction_id: int,
        *,
        status: str = "applied",
    ) -> LoyaltyTransaction | None:
        transaction = await self._accounts.get_transaction_by_id(transaction_id)
        if transaction is None:
            return None
        meta = dict(transaction.meta or {})
        meta["status"] = status
        await self._accounts.update_transaction_meta(transaction, meta=meta)
        await self._session.flush()
        return transaction

    async def restore_points(
        self,
        user_id: int,
        *,
        points: Decimal,
        order_public_id: str,
        reason: str = "cancelled",
    ) -> LoyaltyTransaction:
        if points <= Decimal("0"):
            raise ValueError("Points to restore must be positive.")
        meta = {
            "order_public_id": order_public_id,
            "status": "refunded",
            "reason": reason,
        }
        return await self.adjust_balance(
            user_id,
            amount=points,
            transaction_type=LoyaltyTransactionType.ADJUST,
            reference=order_public_id,
            description="Order loyalty refund",
            meta=meta,
        )

    async def get_transaction(self, transaction_id: int) -> LoyaltyTransaction | None:
        return await self._accounts.get_transaction_by_id(transaction_id)
