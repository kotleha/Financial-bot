"""Store parsed source on bank events.

Revision ID: 20260629_0011
Revises: 20260628_0010
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260629_0011"
down_revision: str | None = "20260628_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_VALUES = "'card', 'cash', 'transfer', 'unknown'"


def upgrade() -> None:
    with op.batch_alter_table("bank_events", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source",
                sa.String(length=32),
                server_default="unknown",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "bank_events_source",
            f"source in ({SOURCE_VALUES})",
        )


def downgrade() -> None:
    with op.batch_alter_table("bank_events", recreate="always") as batch_op:
        batch_op.drop_constraint("bank_events_source", type_="check")
        batch_op.drop_column("source")
