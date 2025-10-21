from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import LoyaltyTransactionType, ReferralRewardType
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class ReferralLink(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "referral_links"

    public_id: Mapped[str] = mapped_column(String(length=36), nullable=False, unique=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(length=32), nullable=False, unique=True)
    reward_type: Mapped[ReferralRewardType] = mapped_column(
        Enum(
            ReferralRewardType,
            native_enum=False,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    reward_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON())
    total_clicks: Mapped[int] = mapped_column(default=0, nullable=False)
    total_signups: Mapped[int] = mapped_column(default=0, nullable=False)
    total_orders: Mapped[int] = mapped_column(default=0, nullable=False)

    owner: Mapped[UserProfile] = relationship("UserProfile", back_populates="referral_links")
    enrollments: Mapped[list["ReferralEnrollment"]] = relationship(
        "ReferralEnrollment",
        back_populates="link",
        cascade="all, delete-orphan",
    )
    rewards: Mapped[list["ReferralReward"]] = relationship(
        "ReferralReward",
        back_populates="link",
        cascade="all, delete-orphan",
    )


class ReferralEnrollment(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "referral_enrollments"

    link_id: Mapped[int] = mapped_column(ForeignKey("referral_links.id", ondelete="CASCADE"), nullable=False)
    referred_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"))
    status: Mapped[str] = mapped_column(String(length=32), nullable=False, default="pending")
    referral_code: Mapped[str | None] = mapped_column(String(length=32))
    meta: Mapped[dict | None] = mapped_column(JSON())

    link: Mapped[ReferralLink] = relationship("ReferralLink", back_populates="enrollments")
    referred_user: Mapped[UserProfile | None] = relationship("UserProfile")


class ReferralReward(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "referral_rewards"

    link_id: Mapped[int] = mapped_column(ForeignKey("referral_links.id", ondelete="CASCADE"), nullable=False)
    referred_user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"))
    reward_type: Mapped[ReferralRewardType] = mapped_column(
        Enum(
            ReferralRewardType,
            native_enum=False,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    reward_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    loyalty_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("loyalty_transactions.id"))
    meta: Mapped[dict | None] = mapped_column(JSON())
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    link: Mapped[ReferralLink] = relationship("ReferralLink", back_populates="rewards")
    referred_user: Mapped[UserProfile | None] = relationship("UserProfile")
    loyalty_transaction: Mapped[LoyaltyTransaction | None] = relationship("LoyaltyTransaction")


from app.infrastructure.db.models.loyalty import LoyaltyTransaction  # noqa: E402
from app.infrastructure.db.models.user import UserProfile  # noqa: E402
