"""Add loyalty, coupon, and referral tables"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20250220_0005"
down_revision: str | None = "20250220_0004"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None

LOYALTY_TRANSACTION_TYPE = sa.Enum(
    "earn",
    "redeem",
    "adjust",
    name="loyaltytransactiontype",
)

COUPON_TYPE = sa.Enum(
    "percent",
    "fixed",
    "shipping",
    name="coupontype",
)

COUPON_STATUS = sa.Enum(
    "active",
    "inactive",
    "expired",
    name="couponstatus",
)

REFERRAL_REWARD_TYPE = sa.Enum(
    "bonus",
    "commission",
    name="referralrewardtype",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    LOYALTY_TRANSACTION_TYPE.create(bind, checkfirst=True)
    COUPON_TYPE.create(bind, checkfirst=True)
    COUPON_STATUS.create(bind, checkfirst=True)
    REFERRAL_REWARD_TYPE.create(bind, checkfirst=True)

    if not inspector.has_table("loyalty_accounts"):
        op.create_table(
            "loyalty_accounts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False, unique=True),
            sa.Column("balance", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("total_earned", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("total_redeemed", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
            sa.Column("meta", sa.JSON(), nullable=True),
        )

    if not inspector.has_table("loyalty_transactions"):
        op.create_table(
            "loyalty_transactions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("account_id", sa.Integer(), sa.ForeignKey("loyalty_accounts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("transaction_type", LOYALTY_TRANSACTION_TYPE, nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("balance_after", sa.Numeric(12, 2), nullable=False),
            sa.Column("reference", sa.String(length=64), nullable=True),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
        )
        op.create_index("ix_loyalty_transactions_account", "loyalty_transactions", ["account_id", "created_at"])

    if not inspector.has_table("coupons"):
        op.create_table(
            "coupons",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("code", sa.String(length=64), nullable=False, unique=True),
            sa.Column("name", sa.String(length=128), nullable=True),
            sa.Column("description", sa.String(length=512), nullable=True),
            sa.Column("coupon_type", COUPON_TYPE, nullable=False),
            sa.Column("status", COUPON_STATUS, nullable=False, server_default="active"),
            sa.Column("amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("percentage", sa.Numeric(5, 2), nullable=True),
            sa.Column("max_discount_amount", sa.Numeric(12, 2), nullable=True),
            sa.Column("min_order_total", sa.Numeric(12, 2), nullable=True),
            sa.Column("max_redemptions", sa.Integer(), nullable=True),
            sa.Column("per_user_limit", sa.Integer(), nullable=True),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("auto_apply", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("meta", sa.JSON(), nullable=True),
        )

    if not inspector.has_table("coupon_redemptions"):
        op.create_table(
            "coupon_redemptions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("coupon_id", sa.Integer(), sa.ForeignKey("coupons.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
            sa.Column("amount_applied", sa.Numeric(12, 2), nullable=False),
            sa.Column("meta", sa.JSON(), nullable=True),
        )
        op.create_index("ix_coupon_redemptions_coupon", "coupon_redemptions", ["coupon_id", "user_id"])

    if not inspector.has_table("referral_links"):
        op.create_table(
            "referral_links",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("public_id", sa.String(length=36), nullable=False, unique=True),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=False),
            sa.Column("code", sa.String(length=32), nullable=False, unique=True),
            sa.Column("reward_type", REFERRAL_REWARD_TYPE, nullable=False),
            sa.Column("reward_value", sa.Numeric(12, 2), nullable=False),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("total_clicks", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_signups", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_orders", sa.Integer(), nullable=False, server_default="0"),
        )

    if not inspector.has_table("referral_enrollments"):
        op.create_table(
            "referral_enrollments",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("link_id", sa.Integer(), sa.ForeignKey("referral_links.id", ondelete="CASCADE"), nullable=False),
            sa.Column("referred_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("referral_code", sa.String(length=32), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
        )

    if not inspector.has_table("referral_rewards"):
        op.create_table(
            "referral_rewards",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("link_id", sa.Integer(), sa.ForeignKey("referral_links.id", ondelete="CASCADE"), nullable=False),
            sa.Column("referred_user_id", sa.Integer(), sa.ForeignKey("user_profiles.id"), nullable=True),
            sa.Column("reward_type", REFERRAL_REWARD_TYPE, nullable=False),
            sa.Column("reward_value", sa.Numeric(12, 2), nullable=False),
            sa.Column("loyalty_transaction_id", sa.Integer(), sa.ForeignKey("loyalty_transactions.id"), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=True),
            sa.Column("rewarded_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_referral_rewards_link", "referral_rewards", ["link_id", "referred_user_id"])


def downgrade() -> None:
    op.drop_index("ix_referral_rewards_link", table_name="referral_rewards")
    op.drop_table("referral_rewards")

    op.drop_table("referral_enrollments")

    op.drop_table("referral_links")

    op.drop_index("ix_coupon_redemptions_coupon", table_name="coupon_redemptions")
    op.drop_table("coupon_redemptions")

    op.drop_table("coupons")

    op.drop_index("ix_loyalty_transactions_account", table_name="loyalty_transactions")
    op.drop_table("loyalty_transactions")

    op.drop_table("loyalty_accounts")

    bind = op.get_bind()
    REFERRAL_REWARD_TYPE.drop(bind, checkfirst=True)
    COUPON_STATUS.drop(bind, checkfirst=True)
    COUPON_TYPE.drop(bind, checkfirst=True)
    LOYALTY_TRANSACTION_TYPE.drop(bind, checkfirst=True)
