from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class UserProfile(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "user_profiles"

    telegram_id: Mapped[int] = mapped_column(BigInteger(), unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(length=32))
    first_name: Mapped[str | None] = mapped_column(String(length=128))
    last_name: Mapped[str | None] = mapped_column(String(length=128))
    language_code: Mapped[str | None] = mapped_column(String(length=8))
    is_blocked: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(length=512))

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="user")

    def display_name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        if self.first_name:
            return self.first_name
        if self.last_name:
            return self.last_name
        return self.username or str(self.telegram_id)
