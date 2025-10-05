"""Expand product summary column"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "20250214_0002"
down_revision: str | None = "20240924_0001"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.alter_column(
        "products",
        "summary",
        existing_type=sa.String(length=512),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "products",
        "summary",
        existing_type=sa.Text(),
        type_=sa.String(length=512),
        existing_nullable=True,
    )
