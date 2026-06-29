"""Track bank event Telegram notification delivery.

Revision ID: 20260627_0006
Revises: 20260626_0005
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_0006"
down_revision: str | None = "20260626_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("bank_events") as batch_op:
        batch_op.add_column(
            sa.Column("telegram_notification_sent_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("telegram_notification_failed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "telegram_notification_attempts",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("bank_events") as batch_op:
        batch_op.drop_column("telegram_notification_attempts")
        batch_op.drop_column("telegram_notification_failed_at")
        batch_op.drop_column("telegram_notification_sent_at")
