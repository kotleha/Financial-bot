from financial_bot.app.domain.categories import DEFAULT_CATEGORIES, DEFAULT_CATEGORY_ALIASES
from financial_bot.app.domain.types import CategoryOwnerRole


def test_default_categories_have_stable_sort_order_and_owner() -> None:
    assert len(DEFAULT_CATEGORIES) == 25
    assert [category.sort_order for category in DEFAULT_CATEGORIES[:17]] == list(range(1, 18))
    assert DEFAULT_CATEGORIES[17].sort_order == 99
    assert [category.sort_order for category in DEFAULT_CATEGORIES[18:]] == list(range(100, 107))
    assert all(category.owner_role for category in DEFAULT_CATEGORIES)


def test_internal_transfer_category_is_excluded_from_expenses() -> None:
    internal_transfer = next(
        category for category in DEFAULT_CATEGORIES if category.code == "internal_transfer"
    )

    assert internal_transfer.owner_role == CategoryOwnerRole.SYSTEM
    assert not internal_transfer.is_expense


def test_income_category_is_excluded_from_expenses() -> None:
    income_categories = [
        category for category in DEFAULT_CATEGORIES if category.code.startswith("income_")
    ]

    assert [category.code for category in income_categories] == [
        "income_general",
        "income_salary",
        "income_advance",
        "income_bonus",
        "income_business",
        "income_debt_return",
        "income_other",
    ]
    assert all(category.owner_role == CategoryOwnerRole.SYSTEM for category in income_categories)
    assert all(not category.is_expense for category in income_categories)


def test_aliases_reference_existing_categories() -> None:
    category_codes = {category.code for category in DEFAULT_CATEGORIES}
    alias_category_codes = {alias.category_code for alias in DEFAULT_CATEGORY_ALIASES}

    assert alias_category_codes <= category_codes
    assert len({alias.alias for alias in DEFAULT_CATEGORY_ALIASES}) == len(DEFAULT_CATEGORY_ALIASES)
