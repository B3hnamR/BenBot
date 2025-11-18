from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, JSON, Numeric, SmallInteger, String, Text
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
    support_tickets: Mapped[list["SupportTicket"]] = relationship("SupportTicket", back_populates="order")
    timelines: Mapped[list["OrderTimeline"]] = relationship(
        "OrderTimeline",
        back_populates="order",
        order_by="OrderTimeline.created_at",
        cascade="all, delete-orphan",
    )
    fulfillment_task: Mapped[Optional["OrderFulfillmentTask"]] = relationship(
        "OrderFulfillmentTask",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )
    feedback: Mapped[Optional["OrderFeedback"]] = relationship(
        "OrderFeedback",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )


class OrderAnswer(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "order_answers"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    question_key: Mapped[str] = mapped_column(String(length=64), nullable=False)
    answer_text: Mapped[str | None] = mapped_column(String(length=1024))
    extra_data: Mapped[dict | None] = mapped_column(JSON())

    order: Mapped[Order] = relationship("Order", back_populates="answers")


class OrderTimeline(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "order_timelines"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(length=32), default="status", nullable=False)
    status: Mapped[str | None] = mapped_column(String(length=32))
    note: Mapped[str | None] = mapped_column(String(length=512))
    actor: Mapped[str | None] = mapped_column(String(length=64))
    meta: Mapped[dict | None] = mapped_column(JSON())

    order: Mapped[Order] = relationship("Order", back_populates="timelines")


class OrderFulfillmentTask(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "order_fulfillment_tasks"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(length=32), default="failed", nullable=False)
    source: Mapped[str | None] = mapped_column(String(length=64))
    last_error: Mapped[str | None] = mapped_column(Text())
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship("Order", back_populates="fulfillment_task")


class AdminActionLog(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "admin_action_logs"

    admin_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    action: Mapped[str] = mapped_column(String(length=64), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    meta: Mapped[dict | None] = mapped_column(JSON())

    order: Mapped[Order | None] = relationship("Order")


class OrderFeedback(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "order_feedback"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text())

    order: Mapped[Order] = relationship("Order", back_populates="feedback")
    user: Mapped["UserProfile"] = relationship("UserProfile")
