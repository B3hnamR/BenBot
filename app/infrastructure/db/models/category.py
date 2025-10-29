from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import Base, IntPKMixin, TimestampMixin


class Category(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(length=128), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(length=128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
    position: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON())

    products: Mapped[list["Product"]] = relationship(
        "Product",
        secondary="product_categories",
        back_populates="categories",
        order_by="Product.position.asc()",
        overlaps="product_links,product",
    )
    product_links: Mapped[list["ProductCategory"]] = relationship(
        "ProductCategory",
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="ProductCategory.position.asc()",
        overlaps="products,categories",
    )


class ProductCategory(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "product_categories"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON())

    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="category_links",
        foreign_keys=[product_id],
        overlaps="categories,product_links",
    )
    category: Mapped[Category] = relationship(
        Category,
        back_populates="product_links",
        foreign_keys=[category_id],
        overlaps="products,category_links",
    )
