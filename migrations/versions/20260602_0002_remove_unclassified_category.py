"""Remove unclassified category from active taxonomy.

Revision ID: 20260602_0002
Revises: 20260601_0001
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260602_0002"
down_revision: str | None = "20260601_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE transactions
        SET category_id = (
            SELECT id FROM categories WHERE code = 'shopping_marketplaces_clothes'
        )
        WHERE category_id = (
            SELECT id FROM categories WHERE code = 'unclassified'
        )
        AND EXISTS (
            SELECT 1 FROM categories WHERE code = 'shopping_marketplaces_clothes'
        )
        """
    )
    op.execute(
        """
        DELETE FROM category_aliases
        WHERE category_id = (SELECT id FROM categories WHERE code = 'unclassified')
        OR alias IN ('неразобранное', 'прочее', 'остальное')
        """
    )
    op.execute(
        """
        UPDATE categories
        SET title = 'Удалено: Неразобранное',
            owner_user_id = NULL,
            owner_role = 'system',
            sort_order = 99,
            is_expense = 0,
            is_active = 0
        WHERE code = 'unclassified'
        """
    )
    op.execute(
        """
        UPDATE categories
        SET sort_order = 11
        WHERE code = 'internal_transfer'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE categories
        SET sort_order = 12
        WHERE code = 'internal_transfer'
        """
    )
    op.execute(
        """
        UPDATE categories
        SET title = 'Неразобранное',
            owner_role = 'wife',
            sort_order = 11,
            is_expense = 1,
            is_active = 1
        WHERE code = 'unclassified'
        """
    )
