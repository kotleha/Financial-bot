"""Add spending limit alert log.

Revision ID: 20260602_0004
Revises: 20260602_0003
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260602_0004"
down_revision: str | None = "20260602_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spending_limit_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("threshold_percent", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("sent_to_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "threshold_percent > 0 and threshold_percent <= 100",
            name=op.f("ck_spending_limit_alerts_spending_limit_alerts_threshold_percent"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_spending_limit_alerts_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["sent_to_user_id"],
            ["users.id"],
            name=op.f("fk_spending_limit_alerts_sent_to_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_spending_limit_alerts_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spending_limit_alerts")),
        sa.UniqueConstraint(
            "period_start",
            "category_id",
            "threshold_percent",
            "sent_to_user_id",
            name=op.f("uq_spending_limit_alerts_period_start"),
        ),
    )
    op.create_index(
        op.f("ix_spending_limit_alerts_category_id"),
        "spending_limit_alerts",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_spending_limit_alerts_period_start"),
        "spending_limit_alerts",
        ["period_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_spending_limit_alerts_period_start"), table_name="spending_limit_alerts")
    op.drop_index(op.f("ix_spending_limit_alerts_category_id"), table_name="spending_limit_alerts")
    op.drop_table("spending_limit_alerts")
