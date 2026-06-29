"""Add detailed income categories.

Revision ID: 20260628_0009
Revises: 20260628_0008
Create Date: 2026-06-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260628_0009"
down_revision: str | None = "20260628_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INCOME_CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("income_salary", "Зарплата", 101),
    ("income_advance", "Аванс", 102),
    ("income_bonus", "Премия/Бонус", 103),
    ("income_business", "Бизнес/Проекты", 104),
    ("income_debt_return", "Возврат долга", 105),
    ("income_other", "Прочий доход", 106),
)


def upgrade() -> None:
    for code, title, sort_order in INCOME_CATEGORIES:
        op.execute(
            f"""
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
                '{code}',
                '{title}',
                NULL,
                'system',
                {sort_order},
                0,
                1
            WHERE NOT EXISTS (
                SELECT 1 FROM categories WHERE code = '{code}'
            )
            """
        )
        op.execute(
            f"""
            UPDATE categories
            SET owner_user_id = NULL,
                owner_role = 'system',
                sort_order = {sort_order},
                is_expense = 0,
                is_active = 1
            WHERE code = '{code}'
            """
        )


def downgrade() -> None:
    for code, _title, sort_order in INCOME_CATEGORIES:
        op.execute(
            f"""
            UPDATE categories
            SET is_active = 0,
                sort_order = {sort_order}
            WHERE code = '{code}'
            """
        )
