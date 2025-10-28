from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class ProductBundleItem(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "product_bundle_items"

    bundle_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    component_product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer(), default=1, nullable=False)
    position: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON())

    bundle: Mapped["Product"] = relationship(
        "Product",
        foreign_keys=[bundle_product_id],
        back_populates="bundle_components",
    )
    component: Mapped["Product"] = relationship(
        "Product",
        foreign_keys=[component_product_id],
        back_populates="bundled_in",
    )
