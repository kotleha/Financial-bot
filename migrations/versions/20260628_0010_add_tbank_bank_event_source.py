"""Add T-Bank bank event source family.

Revision ID: 20260628_0010
Revises: 20260628_0009
Create Date: 2026-06-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260628_0010"
down_revision: str | None = "20260628_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_BANK_VALUES = "'vtb', 'sber', 'unknown'"
NEW_BANK_VALUES = "'vtb', 'sber', 'tbank', 'unknown'"


def upgrade() -> None:
    _replace_bank_check(
        table_name="bank_event_sources",
        constraint_name="bank_event_sources_bank",
        allowed_values=NEW_BANK_VALUES,
    )
    _replace_bank_check(
        table_name="bank_events",
        constraint_name="bank_events_bank",
        allowed_values=NEW_BANK_VALUES,
    )
    _replace_bank_check(
        table_name="bank_category_rules",
        constraint_name="bank_category_rules_bank",
        allowed_values=NEW_BANK_VALUES,
    )


def downgrade() -> None:
    op.execute("update bank_category_rules set bank = 'unknown' where bank = 'tbank'")
    op.execute("update bank_events set bank = 'unknown' where bank = 'tbank'")
    op.execute("update bank_event_sources set bank = 'unknown' where bank = 'tbank'")

    _replace_bank_check(
        table_name="bank_event_sources",
        constraint_name="bank_event_sources_bank",
        allowed_values=OLD_BANK_VALUES,
    )
    _replace_bank_check(
        table_name="bank_events",
        constraint_name="bank_events_bank",
        allowed_values=OLD_BANK_VALUES,
    )
    _replace_bank_check(
        table_name="bank_category_rules",
        constraint_name="bank_category_rules_bank",
        allowed_values=OLD_BANK_VALUES,
    )


def _replace_bank_check(
    *,
    table_name: str,
    constraint_name: str,
    allowed_values: str,
) -> None:
    with op.batch_alter_table(table_name, recreate="always") as batch_op:
        batch_op.drop_constraint(constraint_name, type_="check")
        batch_op.create_check_constraint(
            constraint_name,
            f"bank in ({allowed_values})",
        )
