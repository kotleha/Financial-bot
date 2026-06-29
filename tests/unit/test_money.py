import pytest
from financial_bot.app.domain.money import (
    AmountParseError,
    format_money_minor,
    is_amount_only_text,
    parse_amount_to_minor_units,
    round_minor_to_whole_units_minor,
)


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [
        ("3500", 350000),
        ("3 500", 350000),
        ("3500,50", 350050),
        ("3500.5 ₽", 350050),
        ("3500.555", 350056),
    ],
)
def test_parse_amount_to_minor_units(raw_text: str, expected: int) -> None:
    assert parse_amount_to_minor_units(raw_text) == expected


def test_parse_amount_rejects_invalid_text() -> None:
    with pytest.raises(AmountParseError):
        parse_amount_to_minor_units("abc")


@pytest.mark.parametrize("raw_text", ["20000 99", "20000 18", "12 34"])
def test_parse_amount_rejects_invalid_digit_spacing(raw_text: str) -> None:
    with pytest.raises(AmountParseError):
        parse_amount_to_minor_units(raw_text)


def test_is_amount_only_text() -> None:
    assert is_amount_only_text("3500")
    assert is_amount_only_text("3 500")
    assert is_amount_only_text("3500,50")
    assert is_amount_only_text("3500.50 ₽")
    assert not is_amount_only_text("3500 продукты")
    assert not is_amount_only_text("20000 99")


def test_format_money_minor_rub() -> None:
    assert format_money_minor(350000, "RUB") == "3 500 ₽"
    assert format_money_minor(350050, "RUB") == "3 500,50 ₽"


def test_round_minor_to_whole_units_minor_uses_half_up() -> None:
    assert round_minor_to_whole_units_minor(123449) == 123400
    assert round_minor_to_whole_units_minor(123450) == 123500
    assert round_minor_to_whole_units_minor(-123450) == -123500
