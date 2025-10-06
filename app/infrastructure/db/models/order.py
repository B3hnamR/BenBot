from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import OrderStatus
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class Order(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    public_id: Mapped[str] = mapped_column(String(length=36), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    status: Mapped[OrderStatus] = mapped_column(
        Enum(
            OrderStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=OrderStatus.DRAFT,
        nullable=False,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(length=3), nullable=False)

    invoice_payload: Mapped[str | None] = mapped_column(String(length=128))
    payment_provider: Mapped[str | None] = mapped_column(String(length=64))
    payment_charge_id: Mapped[str | None] = mapped_column(String(length=128))
    payment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(String(length=512))
    extra_attrs: Mapped[dict | None] = mapped_column(JSON())

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="orders")
    product: Mapped["Product"] = relationship("Product")
    answers: Mapped[list["OrderAnswer"]] = relationship(
        "OrderAnswer",
        back_populates="order",
        cascade="all, delete-orphan",
    )


class OrderAnswer(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "order_answers"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    question_key: Mapped[str] = mapped_column(String(length=64), nullable=False)
    answer_text: Mapped[str | None] = mapped_column(String(length=1024))
    extra_data: Mapped[dict | None] = mapped_column(JSON())

    order: Mapped[Order] = relationship("Order", back_populates="answers")
