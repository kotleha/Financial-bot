import pytest
from financial_bot.app.domain.expense_input import (
    is_amount_draft_text,
    is_category_number_only,
    parse_amount_draft,
    parse_amount_with_category_number,
    parse_category_number,
)
from financial_bot.app.domain.types import TransactionScope, UserRole


def test_parse_category_number() -> None:
    assert parse_category_number("7") == 7
    assert parse_category_number(" 17 ") == 17
    assert parse_category_number("18") == 18
    assert parse_category_number("99") == 99


@pytest.mark.parametrize("raw_text", ["0", "19", "3500"])
def test_parse_category_number_rejects_outside_category_range(raw_text: str) -> None:
    with pytest.raises(ValueError):
        parse_category_number(raw_text)


def test_is_category_number_only() -> None:
    assert is_category_number_only("7")
    assert not is_category_number_only("3500")


def test_parse_amount_with_category_number() -> None:
    parsed = parse_amount_with_category_number("3500 2")

    assert parsed.amount == 350000
    assert parsed.category_sort_order == 2


def test_parse_amount_with_category_number_and_comment() -> None:
    parsed = parse_amount_with_category_number("3500 2 магнит")

    assert parsed.amount == 350000
    assert parsed.category_sort_order == 2
    assert parsed.comment == "магнит"


def test_parse_amount_with_category_number_and_scope_prefix() -> None:
    parsed = parse_amount_with_category_number("ж салон 3500 18 бумага")

    assert parsed.amount == 350000
    assert parsed.category_sort_order == 18
    assert parsed.comment == "бумага"
    assert parsed.payer_role == UserRole.WIFE
    assert parsed.scope == TransactionScope.SALON


def test_parse_amount_with_category_number_and_cents() -> None:
    parsed = parse_amount_with_category_number("3500,50 2 магнит")

    assert parsed.amount == 350050
    assert parsed.category_sort_order == 2
    assert parsed.comment == "магнит"


def test_parse_amount_with_internal_transfer_category_number() -> None:
    parsed = parse_amount_with_category_number("20000 99")

    assert parsed.amount == 2000000
    assert parsed.category_sort_order == 99
    assert parsed.comment == ""


def test_parse_amount_draft_accepts_scope_prefix() -> None:
    parsed = parse_amount_draft("салон 3500,50")

    assert parsed.amount == 350050
    assert parsed.scope == TransactionScope.SALON
    assert is_amount_draft_text("дом 3500")
    assert not is_amount_draft_text("дом 3500 18")
