from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
)
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

    service_duration_days: Mapped[int | None] = mapped_column(Integer())
    service_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_paused_total_seconds: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    service_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replacement_of_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))

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
    pause_periods: Mapped[list["OrderPausePeriod"]] = relationship(
        "OrderPausePeriod",
        back_populates="order",
        cascade="all, delete-orphan",
    )
    replacement_parent: Mapped[Optional["Order"]] = relationship(
        "Order",
        remote_side="Order.id",
        back_populates="replacements",
    )
    replacements: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="replacement_parent",
        cascade="all, delete-orphan",
    )
    instant_items: Mapped[list["InstantInventoryItem"]] = relationship(
        "InstantInventoryItem",
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


class OrderPausePeriod(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "order_pause_periods"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(length=255))

    order: Mapped[Order] = relationship("Order", back_populates="pause_periods")


class InstantInventoryItem(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "instant_inventory_items"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(length=255))
    payload: Mapped[str | None] = mapped_column(Text())
    is_consumed: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    meta: Mapped[dict | None] = mapped_column(JSON())

    order: Mapped[Order | None] = relationship("Order", back_populates="instant_items")
    product: Mapped["Product"] = relationship("Product")


from app.infrastructure.db.models.product import Product  # noqa: E402
from app.infrastructure.db.models.user import UserProfile  # noqa: E402
