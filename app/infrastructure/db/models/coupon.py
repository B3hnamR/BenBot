from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CouponStatus, CouponType
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class Coupon(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(String(length=64), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(length=128))
    description: Mapped[str | None] = mapped_column(String(length=512))
    coupon_type: Mapped[CouponType] = mapped_column(
        Enum(
            CouponType,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    status: Mapped[CouponStatus] = mapped_column(
        Enum(
            CouponStatus,
            native_enum=False,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
        default=CouponStatus.ACTIVE,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    max_discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    min_order_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_redemptions: Mapped[int | None] = mapped_column()
    per_user_limit: Mapped[int | None] = mapped_column()
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_apply: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    meta: Mapped[dict | None] = mapped_column(JSON())

    redemptions: Mapped[list["CouponRedemption"]] = relationship(
        "CouponRedemption",
        back_populates="coupon",
        cascade="all, delete-orphan",
    )


class CouponRedemption(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "coupon_redemptions"

    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    amount_applied: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON())

    coupon: Mapped[Coupon] = relationship("Coupon", back_populates="redemptions")
    user: Mapped["UserProfile"] = relationship("UserProfile")
    order: Mapped["Order" | None] = relationship("Order")


from app.infrastructure.db.models.order import Order  # noqa: E402
from app.infrastructure.db.models.user import UserProfile  # noqa: E402
