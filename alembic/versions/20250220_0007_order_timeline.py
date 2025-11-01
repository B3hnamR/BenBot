"""add order timeline table

Revision ID: 20250220_0007
Revises: 20250220_0006
Create Date: 2025-02-20 00:07:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250220_0007"
down_revision = "20250220_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_timelines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False, server_default="status"),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    op.create_index("ix_order_timelines_order", "order_timelines", ["order_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_order_timelines_order", table_name="order_timelines")
    op.drop_table("order_timelines")
