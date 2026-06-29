"""Add explicit bank category rule mode.

Revision ID: 20260629_0012
Revises: 20260629_0011
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0012"
down_revision: str | None = "20260629_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODE_VALUES = "'suggest', 'autosave', 'disabled'"


def upgrade() -> None:
    with op.batch_alter_table("bank_events", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "suggestion_conflict",
                sa.Boolean(),
                server_default="0",
                nullable=False,
            )
        )

    with op.batch_alter_table("bank_category_rules", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mode",
                sa.String(length=32),
                server_default="suggest",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "bank_category_rules_mode",
            f"mode in ({MODE_VALUES})",
        )

    bind = op.get_bind()
    disabled_predicate = "is_active = 0" if bind.dialect.name == "sqlite" else "is_active = false"
    op.execute(
        sa.text(
            f"""
            update bank_category_rules
            set mode = case
                when {disabled_predicate} then 'disabled'
                when hit_count >= 2 then 'autosave'
                else 'suggest'
            end
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("bank_category_rules", recreate="always") as batch_op:
        batch_op.drop_constraint("bank_category_rules_mode", type_="check")
        batch_op.drop_column("mode")

    with op.batch_alter_table("bank_events", recreate="always") as batch_op:
        batch_op.drop_column("suggestion_conflict")
