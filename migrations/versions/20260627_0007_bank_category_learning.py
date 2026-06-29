"""Add learned bank category rules.

Revision ID: 20260627_0007
Revises: 20260627_0006
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0007"
down_revision: str | None = "20260627_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_category_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("bank", sa.String(length=32), nullable=False),
        sa.Column("merchant_key", sa.String(length=255), nullable=False),
        sa.Column("merchant_display", sa.String(length=255), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "bank in ('vtb', 'sber', 'unknown')",
            name=op.f("ck_bank_category_rules_bank_category_rules_bank"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_bank_category_rules_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_bank_category_rules_owner_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_category_rules")),
        sa.UniqueConstraint(
            "owner_user_id",
            "bank",
            "merchant_key",
            name=op.f("uq_bank_category_rules_owner_user_id"),
        ),
    )
    op.create_index(
        op.f("ix_bank_category_rules_category_id"),
        "bank_category_rules",
        ["category_id"],
        unique=False,
    )
    op.create_index(
        "ix_bank_category_rules_owner_bank",
        "bank_category_rules",
        ["owner_user_id", "bank"],
        unique=False,
    )

    with op.batch_alter_table("bank_events") as batch_op:
        batch_op.add_column(
            sa.Column("suggested_category_source", sa.String(length=32), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("bank_events") as batch_op:
        batch_op.drop_column("suggested_category_source")

    op.drop_index("ix_bank_category_rules_owner_bank", table_name="bank_category_rules")
    op.drop_index(op.f("ix_bank_category_rules_category_id"), table_name="bank_category_rules")
    op.drop_table("bank_category_rules")
