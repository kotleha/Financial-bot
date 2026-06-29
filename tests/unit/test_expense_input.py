import pytest
from financial_bot.app.domain.expense_input import (
    is_category_number_only,
    parse_amount_with_category_number,
    parse_category_number,
)


def test_parse_category_number() -> None:
    assert parse_category_number("7") == 7
    assert parse_category_number(" 17 ") == 17
    assert parse_category_number("99") == 99


@pytest.mark.parametrize("raw_text", ["0", "18", "3500"])
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
