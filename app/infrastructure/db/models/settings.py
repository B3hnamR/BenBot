from __future__ import annotations

from sqlalchemy import Boolean, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class AppSetting(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(length=128), unique=True, nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON())


class RequiredChannel(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "required_channels"

    channel_id: Mapped[int | None] = mapped_column(unique=True, nullable=True)
    username: Mapped[str | None] = mapped_column(String(length=64))
    title: Mapped[str | None] = mapped_column(String(length=255))
    invite_link: Mapped[str | None] = mapped_column(String(length=255))
    is_mandatory: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
