"""Add bank event ingestion tables.

Revision ID: 20260626_0005
Revises: 20260602_0004
Create Date: 2026-06-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_0005"
down_revision: str | None = "20260602_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_event_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("bank", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "bank in ('vtb', 'sber', 'unknown')",
            name=op.f("ck_bank_event_sources_bank_event_sources_bank"),
        ),
        sa.CheckConstraint(
            "channel in ('ios_shortcut', 'manual_telegram', 'email', 'android_notification')",
            name=op.f("ck_bank_event_sources_bank_event_sources_channel"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_bank_event_sources_owner_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_event_sources")),
        sa.UniqueConstraint("code", name=op.f("uq_bank_event_sources_code")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_bank_event_sources_token_hash")),
    )
    op.create_index(
        op.f("ix_bank_event_sources_code"),
        "bank_event_sources",
        ["code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bank_event_sources_owner_user_id"),
        "bank_event_sources",
        ["owner_user_id"],
        unique=False,
    )

    op.create_table(
        "bank_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("bank", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operation_kind", sa.String(length=32), nullable=False),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=True),
        sa.Column("fee_amount", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="RUB", nullable=False),
        sa.Column("merchant", sa.String(length=255), nullable=True),
        sa.Column("counterparty", sa.String(length=255), nullable=True),
        sa.Column("redacted_text", sa.String(length=2000), nullable=False),
        sa.Column("normalized_text_hash", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("suggested_category_id", sa.Integer(), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("raw_text_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount is null or amount > 0",
            name=op.f("ck_bank_events_bank_events_amount_positive"),
        ),
        sa.CheckConstraint(
            "fee_amount is null or fee_amount >= 0",
            name=op.f("ck_bank_events_bank_events_fee_amount_non_negative"),
        ),
        sa.CheckConstraint(
            "bank in ('vtb', 'sber', 'unknown')",
            name=op.f("ck_bank_events_bank_events_bank"),
        ),
        sa.CheckConstraint(
            "channel in ('ios_shortcut', 'manual_telegram', 'email', 'android_notification')",
            name=op.f("ck_bank_events_bank_events_channel"),
        ),
        sa.CheckConstraint(
            (
                "operation_kind in ('expense_candidate', 'income', 'internal_transfer', "
                "'refund', 'ignored', 'unknown')"
            ),
            name=op.f("ck_bank_events_bank_events_operation_kind"),
        ),
        sa.CheckConstraint(
            (
                "parse_status in ('ignored', 'parsed', 'needs_confirmation', 'confirmed', "
                "'rejected', 'autosaved')"
            ),
            name=op.f("ck_bank_events_bank_events_parse_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["bank_event_sources.id"],
            name=op.f("fk_bank_events_source_id_bank_event_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["suggested_category_id"],
            ["categories.id"],
            name=op.f("fk_bank_events_suggested_category_id_categories"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["transactions.id"],
            name=op.f("fk_bank_events_transaction_id_transactions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bank_events")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_bank_events_dedupe_key")),
    )
    op.create_index(
        op.f("ix_bank_events_normalized_text_hash"),
        "bank_events",
        ["normalized_text_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bank_events_parse_status"),
        "bank_events",
        ["parse_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bank_events_received_at"),
        "bank_events",
        ["received_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bank_events_source_id"),
        "bank_events",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bank_events_transaction_id"),
        "bank_events",
        ["transaction_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_bank_events_transaction_id"), table_name="bank_events")
    op.drop_index(op.f("ix_bank_events_source_id"), table_name="bank_events")
    op.drop_index(op.f("ix_bank_events_received_at"), table_name="bank_events")
    op.drop_index(op.f("ix_bank_events_parse_status"), table_name="bank_events")
    op.drop_index(op.f("ix_bank_events_normalized_text_hash"), table_name="bank_events")
    op.drop_table("bank_events")
    op.drop_index(op.f("ix_bank_event_sources_owner_user_id"), table_name="bank_event_sources")
    op.drop_index(op.f("ix_bank_event_sources_code"), table_name="bank_event_sources")
    op.drop_table("bank_event_sources")
