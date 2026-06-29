"""Add system income category.

Revision ID: 20260628_0008
Revises: 20260627_0007
Create Date: 2026-06-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260628_0008"
down_revision: str | None = "20260627_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO categories (
            code,
            title,
            owner_user_id,
            owner_role,
            sort_order,
            is_expense,
            is_active
        )
        SELECT
            'income_general',
            'Доходы',
            NULL,
            'system',
            100,
            0,
            1
        WHERE NOT EXISTS (
            SELECT 1 FROM categories WHERE code = 'income_general'
        )
        """
    )
    op.execute(
        """
        UPDATE categories
        SET owner_user_id = NULL,
            owner_role = 'system',
            sort_order = 100,
            is_expense = 0,
            is_active = 1
        WHERE code = 'income_general'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE categories
        SET is_active = 0,
            sort_order = 100
        WHERE code = 'income_general'
        """
    )
