"""Add categories, bundles, and inventory limits"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20250220_0006"
down_revision: str | None = "20250220_0005"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("categories"):
        op.create_table(
            "categories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("name", sa.String(length=128), nullable=False, unique=True),
            sa.Column("slug", sa.String(length=128), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("meta", sa.JSON(), nullable=True),
        )

    if not inspector.has_table("product_categories"):
        op.create_table(
            "product_categories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.UniqueConstraint(
                "product_id",
                "category_id",
                name="uq_product_categories_product_category",
            ),
        )
        op.create_index(
            "ix_product_categories_product_id",
            "product_categories",
            ["product_id"],
        )
        op.create_index(
            "ix_product_categories_category_id",
            "product_categories",
            ["category_id"],
        )

    if not inspector.has_table("product_bundle_items"):
        op.create_table(
            "product_bundle_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "bundle_product_id",
                sa.Integer(),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "component_product_id",
                sa.Integer(),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.CheckConstraint("quantity > 0", name="ck_product_bundle_items_quantity_positive"),
            sa.UniqueConstraint(
                "bundle_product_id",
                "component_product_id",
                name="uq_product_bundle_unique_component",
            ),
        )
        op.create_index(
            "ix_product_bundle_items_bundle",
            "product_bundle_items",
            ["bundle_product_id"],
        )
        op.create_index(
            "ix_product_bundle_items_component",
            "product_bundle_items",
            ["component_product_id"],
        )

    existing_columns = {column["name"] for column in inspector.get_columns("products")}

    with op.batch_alter_table("products") as batch_op:
        if "max_per_order" not in existing_columns:
            batch_op.add_column(sa.Column("max_per_order", sa.Integer(), nullable=True))
        if "inventory_threshold" not in existing_columns:
            batch_op.add_column(sa.Column("inventory_threshold", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("products") as batch_op:
        batch_op.drop_column("inventory_threshold")
        batch_op.drop_column("max_per_order")

    op.drop_index("ix_product_bundle_items_component", table_name="product_bundle_items")
    op.drop_index("ix_product_bundle_items_bundle", table_name="product_bundle_items")
    op.drop_table("product_bundle_items")

    op.drop_index("ix_product_categories_category_id", table_name="product_categories")
    op.drop_index("ix_product_categories_product_id", table_name="product_categories")
    op.drop_table("product_categories")

    op.drop_table("categories")
