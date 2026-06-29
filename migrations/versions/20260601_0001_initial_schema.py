"""Initial database schema.

Revision ID: 20260601_0001
Revises:
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260601_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role in ('husband', 'wife')", name=op.f("ck_users_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("role", name=op.f("uq_users_role")),
        sa.UniqueConstraint("telegram_id", name=op.f("uq_users_telegram_id")),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=False)

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("owner_role", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_expense", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "owner_role in ('husband', 'wife', 'system')",
            name=op.f("ck_categories_categories_owner_role"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_categories_owner_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("code", name=op.f("uq_categories_code")),
    )
    op.create_index(op.f("ix_categories_code"), "categories", ["code"], unique=False)

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
        sa.UniqueConstraint("key", name=op.f("uq_settings_key")),
    )
    op.create_index(op.f("ix_settings_key"), "settings", ["key"], unique=False)

    op.create_table(
        "category_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_category_aliases_category_id_categories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_aliases")),
        sa.UniqueConstraint("alias", name=op.f("uq_category_aliases_alias")),
    )
    op.create_index(
        op.f("ix_category_aliases_alias"),
        "category_aliases",
        ["alias"],
        unique=False,
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payer_user_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), server_default="unknown", nullable=False),
        sa.Column("comment", sa.String(length=1000), nullable=True),
        sa.Column("raw_text", sa.String(length=2000), nullable=True),
        sa.Column("included_in_reports", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name=op.f("ck_transactions_transactions_amount_positive")),
        sa.CheckConstraint(
            "source in ('card', 'cash', 'transfer', 'unknown')",
            name=op.f("ck_transactions_transactions_source"),
        ),
        sa.CheckConstraint(
            "type in ('expense', 'income', 'internal_transfer', 'correction')",
            name=op.f("ck_transactions_transactions_type"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_transactions_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_transactions_created_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["payer_user_id"],
            ["users.id"],
            name=op.f("fk_transactions_payer_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(
        op.f("ix_transactions_category_id"), "transactions", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_transactions_occurred_at"), "transactions", ["occurred_at"], unique=False
    )
    op.create_index(
        op.f("ix_transactions_payer_user_id"), "transactions", ["payer_user_id"], unique=False
    )

    op.create_table(
        "operation_audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("changed_by_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "action in ('create', 'update', 'delete')",
            name=op.f("ck_operation_audit_log_operation_audit_log_action"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by_user_id"],
            ["users.id"],
            name=op.f("fk_operation_audit_log_changed_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_operation_audit_log_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operation_audit_log")),
    )
    op.create_index(
        op.f("ix_operation_audit_log_transaction_id"),
        "operation_audit_log",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_operation_audit_log_transaction_id"), table_name="operation_audit_log")
    op.drop_table("operation_audit_log")
    op.drop_index(op.f("ix_transactions_payer_user_id"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_occurred_at"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_category_id"), table_name="transactions")
    op.drop_table("transactions")
    op.drop_index(op.f("ix_category_aliases_alias"), table_name="category_aliases")
    op.drop_table("category_aliases")
    op.drop_index(op.f("ix_settings_key"), table_name="settings")
    op.drop_table("settings")
    op.drop_index(op.f("ix_categories_code"), table_name="categories")
    op.drop_table("categories")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
