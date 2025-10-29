from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.infrastructure.db.models import LoyaltyAccount, LoyaltyTransaction

from .base import BaseRepository


class LoyaltyRepository(BaseRepository):
    async def get_account_by_user(self, user_id: int) -> LoyaltyAccount | None:
        result = await self.session.execute(
            select(LoyaltyAccount).where(LoyaltyAccount.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def create_account(self, user_id: int) -> LoyaltyAccount:
        account = LoyaltyAccount(user_id=user_id)
        await self.add(account)
        return account

    async def add_transaction(
        self,
        account: LoyaltyAccount,
        *,
        transaction_type,
        amount: Decimal,
        balance_after: Decimal,
        reference: str | None = None,
        description: str | None = None,
        meta: dict | None = None,
    ) -> LoyaltyTransaction:
        txn = LoyaltyTransaction(
            account=account,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=balance_after,
            reference=reference,
            description=description,
            meta=meta,
        )
        await self.add(txn)
        return txn

    async def update_account_totals(
        self,
        account: LoyaltyAccount,
        *,
        balance: Decimal,
        earned_delta: Decimal = Decimal("0"),
        redeemed_delta: Decimal = Decimal("0"),
    ) -> LoyaltyAccount:
        account.balance = balance
        account.total_earned = (account.total_earned or Decimal("0")) + earned_delta
        account.total_redeemed = (account.total_redeemed or Decimal("0")) + redeemed_delta
        return account

    async def get_transaction_by_id(self, transaction_id: int) -> LoyaltyTransaction | None:
        result = await self.session.execute(
            select(LoyaltyTransaction).where(LoyaltyTransaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    async def update_transaction_meta(
        self,
        transaction: LoyaltyTransaction,
        *,
        meta: dict | None,
    ) -> LoyaltyTransaction:
        transaction.meta = meta
        return transaction
