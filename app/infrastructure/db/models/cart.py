from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CartAdjustmentType, CartStatus
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class ShoppingCart(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "shopping_carts"

    public_id: Mapped[str] = mapped_column(String(length=36), unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user_profiles.id"), nullable=True)
    status: Mapped[CartStatus] = mapped_column(
        Enum(
            CartStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=CartStatus.ACTIVE,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(length=3), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subtotal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    shipping_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    discount_code: Mapped[str | None] = mapped_column(String(length=64))
    notes: Mapped[str | None] = mapped_column(Text())
    meta: Mapped[dict | None] = mapped_column(JSON())

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="carts")
    items: Mapped[list["CartItem"]] = relationship(
        "CartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartItem.position.asc()",
    )
    adjustments: Mapped[list["CartAdjustment"]] = relationship(
        "CartAdjustment",
        back_populates="cart",
        cascade="all, delete-orphan",
        order_by="CartAdjustment.created_at.asc()",
    )


class CartItem(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "cart_items"

    cart_id: Mapped[int] = mapped_column(ForeignKey("shopping_carts.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(length=3), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    title_override: Mapped[str | None] = mapped_column(String(length=255))
    position: Mapped[int] = mapped_column(default=0, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON())

    cart: Mapped[ShoppingCart] = relationship("ShoppingCart", back_populates="items")
    product: Mapped["Product"] = relationship("Product")


class CartAdjustment(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "cart_adjustments"

    cart_id: Mapped[int] = mapped_column(ForeignKey("shopping_carts.id"), nullable=False)
    kind: Mapped[CartAdjustmentType] = mapped_column(
        Enum(
            CartAdjustmentType,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    code: Mapped[str | None] = mapped_column(String(length=64))
    title: Mapped[str | None] = mapped_column(String(length=255))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON())

    cart: Mapped[ShoppingCart] = relationship("ShoppingCart", back_populates="adjustments")


from app.infrastructure.db.models.user import UserProfile  # noqa: E402
from app.infrastructure.db.models.product import Product  # noqa: E402

