from __future__ import annotations

from sqlalchemy import Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ProductRelationType
from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class ProductRelation(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "product_relations"

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    related_product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    relation_type: Mapped[ProductRelationType] = mapped_column(
        Enum(
            ProductRelationType,
            native_enum=False,
            length=32,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        nullable=False,
    )
    weight: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)

    product: Mapped["Product"] = relationship(
        "Product",
        foreign_keys=[product_id],
        back_populates="related_products",
    )
    related_product: Mapped["Product"] = relationship(
        "Product",
        foreign_keys=[related_product_id],
        back_populates="related_to",
    )


from app.infrastructure.db.models.product import Product  # noqa: E402
