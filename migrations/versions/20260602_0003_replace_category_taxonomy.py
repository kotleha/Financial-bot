"""Replace active category taxonomy with shared spending categories.

Revision ID: 20260602_0003
Revises: 20260602_0002
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260602_0003"
down_revision: str | None = "20260602_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_CATEGORY_CODES = (
    "home_obligatory",
    "private_transfers_tips",
    "vacation_travel",
    "transport",
    "subscriptions_digital",
    "flowers_gifts_from_you",
    "groceries_household",
    "cafes_delivery",
    "shopping_marketplaces_clothes",
    "health_services_beauty",
)


def upgrade() -> None:
    quoted_codes = ", ".join(f"'{code}'" for code in OLD_CATEGORY_CODES)
    op.execute(
        f"""
        DELETE FROM category_aliases
        WHERE category_id IN (
            SELECT id FROM categories WHERE code IN ({quoted_codes})
        )
        """
    )
    op.execute(
        f"""
        UPDATE categories
        SET owner_user_id = NULL,
            owner_role = 'system',
            sort_order = sort_order + 100,
            is_active = 0
        WHERE code IN ({quoted_codes})
        """
    )
    op.execute(
        """
        UPDATE categories
        SET title = 'Самоперевод / внутренний перевод',
            owner_user_id = NULL,
            owner_role = 'system',
            sort_order = 99,
            is_expense = 0,
            is_active = 1
        WHERE code = 'internal_transfer'
        """
    )


def downgrade() -> None:
    old_category_updates = (
        ("home_obligatory", "Дом / обязательные платежи", "husband", 1),
        ("private_transfers_tips", "Частные переводы / оплаты людям / чаевые", "husband", 2),
        ("vacation_travel", "Поездка / отпуск", "husband", 3),
        ("transport", "Транспорт", "husband", 4),
        ("subscriptions_digital", "Подписки / цифровые сервисы", "husband", 5),
        ("flowers_gifts_from_you", "Цветы / подарки от вас", "husband", 6),
        ("groceries_household", "Продукты / хозбыт", "wife", 7),
        ("cafes_delivery", "Кафе / рестораны / доставка", "wife", 8),
        (
            "shopping_marketplaces_clothes",
            "Онлайн-покупки / маркетплейсы / одежда",
            "wife",
            9,
        ),
        ("health_services_beauty", "Здоровье / услуги / красота / аптеки", "wife", 10),
    )
    for code, title, owner_role, sort_order in old_category_updates:
        op.execute(
            f"""
            UPDATE categories
            SET title = '{title}',
                owner_role = '{owner_role}',
                sort_order = {sort_order},
                is_expense = 1,
                is_active = 1
            WHERE code = '{code}'
            """
        )

    op.execute(
        """
        UPDATE categories
        SET sort_order = 11,
            is_expense = 0,
            is_active = 1
        WHERE code = 'internal_transfer'
        """
    )
