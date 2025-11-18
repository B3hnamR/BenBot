"""add fulfillment tasks, admin logs, and feedback tables

Revision ID: 20250225_0008
Revises: 20250220_0007
Create Date: 2025-11-03 10:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250225_0008"
down_revision = "20250220_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "order_fulfillment_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="failed"),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_order_fulfillment_tasks_status",
        "order_fulfillment_tasks",
        ["status"],
    )

    op.create_table(
        "admin_action_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    op.create_index("ix_admin_action_logs_admin", "admin_action_logs", ["admin_id", "action"])

    op.create_table(
        "order_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_index("ix_order_feedback_rating", "order_feedback", ["rating"])


def downgrade() -> None:
    op.drop_index("ix_order_feedback_rating", table_name="order_feedback")
    op.drop_table("order_feedback")
    op.drop_index("ix_admin_action_logs_admin", table_name="admin_action_logs")
    op.drop_table("admin_action_logs")
    op.drop_index("ix_order_fulfillment_tasks_status", table_name="order_fulfillment_tasks")
    op.drop_table("order_fulfillment_tasks")
