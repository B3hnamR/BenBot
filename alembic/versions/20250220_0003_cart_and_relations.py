"""Add shopping carts, cart items, adjustments, and product relations"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "20250220_0003"
down_revision: str | None = "20250214_0002"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

CART_STATUS = sa.Enum(
    "active",
    "checked_out",
    "abandoned",
    name="cartstatus",
)

CART_ADJUSTMENT_TYPE = sa.Enum(
    "promotion",
    "tax",
    "shipping",
    "fee",
    name="cartadjustmenttype",
)

PRODUCT_RELATION_TYPE = sa.Enum(
    "related",
    "upsell",
    "cross_sell",
    "accessory",
    name="productrelationtype",
)


def upgrade() -> None:
    CART_STATUS.create(op.get_bind(), checkfirst=True)
    CART_ADJUSTMENT_TYPE.create(op.get_bind(), checkfirst=True)
    PRODUCT_RELATION_TYPE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "shopping_carts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=True),
        sa.Column("status", CART_STATUS, nullable=False, server_default="active"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subtotal_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("shipping_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("discount_code", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    op.create_index("ix_shopping_carts_user_id", "shopping_carts", ["user_id"])
    op.create_index("ix_shopping_carts_status", "shopping_carts", ["status"])

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("cart_id", sa.Integer(), sa.ForeignKey("shopping_carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("title_override", sa.String(length=255), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_cart_product", "cart_items", ["cart_id", "product_id"], unique=True)

    op.create_table(
        "cart_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("cart_id", sa.Integer(), sa.ForeignKey("shopping_carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", CART_ADJUSTMENT_TYPE, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    op.create_index("ix_cart_adjustments_cart_id", "cart_adjustments", ["cart_id"])

    op.create_table(
        "product_relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("related_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", PRODUCT_RELATION_TYPE, nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_product_relations_product_type",
        "product_relations",
        ["product_id", "relation_type", "weight"],
    )
    op.create_unique_constraint(
        "uq_product_relations_unique",
        "product_relations",
        ["product_id", "related_product_id", "relation_type"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_product_relations_unique", "product_relations", type_="unique")
    op.drop_index("ix_product_relations_product_type", table_name="product_relations")
    op.drop_table("product_relations")

    op.drop_index("ix_cart_adjustments_cart_id", table_name="cart_adjustments")
    op.drop_table("cart_adjustments")

    op.drop_index("ix_cart_items_cart_product", table_name="cart_items")
    op.drop_index("ix_cart_items_cart_id", table_name="cart_items")
    op.drop_table("cart_items")

    op.drop_index("ix_shopping_carts_status", table_name="shopping_carts")
    op.drop_index("ix_shopping_carts_user_id", table_name="shopping_carts")
    op.drop_table("shopping_carts")

    PRODUCT_RELATION_TYPE.drop(op.get_bind(), checkfirst=True)
    CART_ADJUSTMENT_TYPE.drop(op.get_bind(), checkfirst=True)
    CART_STATUS.drop(op.get_bind(), checkfirst=True)
