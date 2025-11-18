"""service duration tracking and instant inventory

Revision ID: 20250225_0009
Revises: 20250225_0008
Create Date: 2025-11-18 12:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250225_0009"
down_revision = "20250225_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("service_duration_days", sa.Integer(), nullable=True))
    op.add_column(
        "products",
        sa.Column("instant_delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column("orders", sa.Column("service_duration_days", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("service_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "orders",
        sa.Column("service_paused_total_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("orders", sa.Column("service_paused_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("replacement_of_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_orders_replacement_of_id",
        "orders",
        "orders",
        ["replacement_of_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "order_pause_periods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "instant_inventory_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("is_consumed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("instant_inventory_items")
    op.drop_table("order_pause_periods")
    op.drop_constraint("fk_orders_replacement_of_id", "orders", type_="foreignkey")
    op.drop_column("orders", "replacement_of_id")
    op.drop_column("orders", "service_paused_at")
    op.drop_column("orders", "service_paused_total_seconds")
    op.drop_column("orders", "service_started_at")
    op.drop_column("orders", "service_duration_days")
    op.drop_column("products", "instant_delivery_enabled")
    op.drop_column("products", "service_duration_days")
