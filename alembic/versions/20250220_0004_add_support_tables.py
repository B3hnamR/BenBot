"""Add support ticket tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "20250220_0004"
down_revision: str | None = "20250220_0003"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

SUPPORT_TICKET_STATUS = sa.Enum(
    "open",
    "awaiting_user",
    "awaiting_admin",
    "resolved",
    "archived",
    name="supportticketstatus",
)

SUPPORT_TICKET_PRIORITY = sa.Enum(
    "low",
    "normal",
    "high",
    "urgent",
    name="supportticketpriority",
)

SUPPORT_AUTHOR_ROLE = sa.Enum(
    "user",
    "admin",
    "system",
    name="supportauthorrole",
)


def upgrade() -> None:
    bind = op.get_bind()
    SUPPORT_TICKET_STATUS.create(bind, checkfirst=True)
    SUPPORT_TICKET_PRIORITY.create(bind, checkfirst=True)
    SUPPORT_AUTHOR_ROLE.create(bind, checkfirst=True)

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("status", SUPPORT_TICKET_STATUS, nullable=False, server_default="open"),
        sa.Column("priority", SUPPORT_TICKET_PRIORITY, nullable=False, server_default="normal"),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("assigned_admin_id", sa.BigInteger(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
    )
    op.create_index("ix_support_tickets_user", "support_tickets", ["user_id", "last_activity_at"])
    op.create_index("ix_support_tickets_order", "support_tickets", ["order_id"])

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_role", SUPPORT_AUTHOR_ROLE, nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
    )
    op.create_index("ix_support_messages_ticket", "support_messages", ["ticket_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_support_messages_ticket", table_name="support_messages")
    op.drop_table("support_messages")

    op.drop_index("ix_support_tickets_order", table_name="support_tickets")
    op.drop_index("ix_support_tickets_user", table_name="support_tickets")
    op.drop_table("support_tickets")

    bind = op.get_bind()
    SUPPORT_AUTHOR_ROLE.drop(bind, checkfirst=True)
    SUPPORT_TICKET_PRIORITY.drop(bind, checkfirst=True)
    SUPPORT_TICKET_STATUS.drop(bind, checkfirst=True)
