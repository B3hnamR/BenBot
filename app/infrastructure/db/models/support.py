from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SupportAuthorRole, SupportTicketPriority, SupportTicketStatus
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class SupportTicket(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"

    public_id: Mapped[str] = mapped_column(String(length=36), unique=True, nullable=False, default=lambda: str(uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))

    status: Mapped[SupportTicketStatus] = mapped_column(
        Enum(
            SupportTicketStatus,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=SupportTicketStatus.OPEN,
        nullable=False,
    )
    priority: Mapped[SupportTicketPriority] = mapped_column(
        Enum(
            SupportTicketPriority,
            native_enum=False,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=SupportTicketPriority.NORMAL,
        nullable=False,
    )
    category: Mapped[str | None] = mapped_column(String(length=64))
    subject: Mapped[str] = mapped_column(String(length=160))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(tz=timezone.utc),
    )
    assigned_admin_id: Mapped[int | None] = mapped_column(nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON())

    user: Mapped["UserProfile"] = relationship("UserProfile", back_populates="support_tickets")
    order: Mapped["Order"] = relationship("Order", back_populates="support_tickets")
    messages: Mapped[list["SupportMessage"]] = relationship(
        "SupportMessage",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="SupportMessage.created_at.asc()",
    )


class SupportMessage(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "support_messages"

    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id"), nullable=False)
    author_role: Mapped[SupportAuthorRole] = mapped_column(
        Enum(
            SupportAuthorRole,
            native_enum=False,
            length=16,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    author_id: Mapped[int | None] = mapped_column(nullable=True)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON())

    ticket: Mapped[SupportTicket] = relationship("SupportTicket", back_populates="messages")
