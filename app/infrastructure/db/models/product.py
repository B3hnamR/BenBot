from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class Product(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(length=255), nullable=False)
    slug: Mapped[str] = mapped_column(String(length=255), nullable=False, unique=True)
    summary: Mapped[str | None] = mapped_column(Text())
    description: Mapped[str | None] = mapped_column(Text())
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(length=3), default="USD", nullable=False)
    inventory: Mapped[int | None] = mapped_column(Integer())
    max_per_order: Mapped[int | None] = mapped_column(Integer())
    inventory_threshold: Mapped[int | None] = mapped_column(Integer())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    service_duration_days: Mapped[int | None] = mapped_column(Integer())
    instant_delivery_enabled: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    extra_attrs: Mapped[dict | None] = mapped_column(JSON())

    questions: Mapped[list["ProductQuestion"]] = relationship(
        "ProductQuestion",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductQuestion.position.asc()",
    )
    related_products: Mapped[list["ProductRelation"]] = relationship(
        "ProductRelation",
        foreign_keys="ProductRelation.product_id",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    related_to: Mapped[list["ProductRelation"]] = relationship(
        "ProductRelation",
        foreign_keys="ProductRelation.related_product_id",
        back_populates="related_product",
        cascade="all, delete-orphan",
    )
    categories: Mapped[list["Category"]] = relationship(
        "Category",
        secondary="product_categories",
        back_populates="products",
        order_by="Category.position.asc()",
        overlaps="category_links,product",
    )
    category_links: Mapped[list["ProductCategory"]] = relationship(
        "ProductCategory",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductCategory.position.asc()",
        overlaps="categories,category",
    )
    bundle_components: Mapped[list["ProductBundleItem"]] = relationship(
        "ProductBundleItem",
        foreign_keys="ProductBundleItem.bundle_product_id",
        back_populates="bundle",
        cascade="all, delete-orphan",
    )
    bundled_in: Mapped[list["ProductBundleItem"]] = relationship(
        "ProductBundleItem",
        foreign_keys="ProductBundleItem.component_product_id",
        back_populates="component",
        cascade="all, delete-orphan",
    )


from app.infrastructure.db.models.category import Category, ProductCategory  # noqa: E402
from app.infrastructure.db.models.product_bundle import ProductBundleItem  # noqa: E402
from app.infrastructure.db.models.product_relation import ProductRelation  # noqa: E402
