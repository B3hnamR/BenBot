from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import LoyaltyTransactionType
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class LoyaltyAccount(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_accounts"

    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), nullable=False, unique=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_earned: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total_redeemed: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    meta: Mapped[dict | None] = mapped_column(JSON())

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="loyalty_account")
    transactions: Mapped[list["LoyaltyTransaction"]] = relationship(
        "LoyaltyTransaction",
        back_populates="account",
        cascade="all, delete-orphan",
        order_by="LoyaltyTransaction.created_at.desc()",
    )


class LoyaltyTransaction(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_transactions"

    account_id: Mapped[int] = mapped_column(ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), nullable=False)
    transaction_type: Mapped[LoyaltyTransactionType] = mapped_column(
        Enum(
            LoyaltyTransactionType,
            native_enum=False,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(length=64))
    description: Mapped[str | None] = mapped_column(String(length=255))
    meta: Mapped[dict | None] = mapped_column(JSON())

    account: Mapped[LoyaltyAccount] = relationship("LoyaltyAccount", back_populates="transactions")


from app.infrastructure.db.models.user import UserProfile  # noqa: E402
