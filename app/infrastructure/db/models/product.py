from __future__ import annotations

from decimal import Decimal
from typing import List

from sqlalchemy import Boolean, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class Product(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    slug: Mapped[str] = mapped_column(String(length=255), nullable=False, unique=True)
    summary: Mapped[str | None] = mapped_column(String(length=512))
    description: Mapped[str | None] = mapped_column(Text())
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(length=3), default="USD", nullable=False)
    inventory: Mapped[int | None] = mapped_column(Integer())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    extra_attrs: Mapped[dict | None] = mapped_column(JSON())

    questions: Mapped[list["ProductQuestion"]] = relationship(
        "ProductQuestion",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductQuestion.position.asc()",
    )
