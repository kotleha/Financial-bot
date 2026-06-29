import pytest
from financial_bot.app.domain.expense_input import (
    is_internal_transfer_tail,
    parse_free_text_expense,
)
from financial_bot.app.domain.types import TransactionSource, UserRole


def test_parse_free_text_expense() -> None:
    parsed = parse_free_text_expense("3500 продукты магнит")

    assert parsed.amount == 350000
    assert parsed.tail == "продукты магнит"
    assert parsed.source == TransactionSource.UNKNOWN
    assert parsed.payer_role is None


def test_parse_free_text_expense_with_source() -> None:
    parsed = parse_free_text_expense("110000 отпуск наличные")

    assert parsed.amount == 11000000
    assert parsed.source == TransactionSource.CASH


def test_parse_free_text_expense_detects_source_by_token_boundaries() -> None:
    transfer = parse_free_text_expense("18500 перевод Алексей")
    not_transfer = parse_free_text_expense("18500 суперперевод кафе")

    assert transfer.source == TransactionSource.TRANSFER
    assert not_transfer.source == TransactionSource.UNKNOWN


def test_parse_free_text_expense_with_explicit_payer() -> None:
    parsed = parse_free_text_expense("ж 4200 кафе")

    assert parsed.amount == 420000
    assert parsed.payer_role == UserRole.WIFE


def test_parse_free_text_expense_with_dot_cents() -> None:
    parsed = parse_free_text_expense("3500.50 продукты магнит")

    assert parsed.amount == 350050
    assert parsed.tail == "продукты магнит"


@pytest.mark.parametrize(
    "tail",
    [
        "сам себе",
        "себе",
        "жене",
        "мужу",
        "перевод жене",
        "жене перевёл",
        "мужу перевел",
        "скинул супруге",
        "перевод себе",
        "скинул себе",
        "самоперевод",
        "внутренний перевод",
        "между нами",
        "между своими счетами",
    ],
)
def test_is_internal_transfer_tail_accepts_family_transfers(tail: str) -> None:
    assert is_internal_transfer_tail(tail)


@pytest.mark.parametrize(
    "tail",
    [
        "перевод внешний чаевые",
        "жене кафе",
        "подарок жене",
        "мужу ресторан",
        "подарок себе",
        "себе кафе",
        "для себя одежда",
    ],
)
def test_is_internal_transfer_tail_rejects_external_or_categorized_expenses(tail: str) -> None:
    assert not is_internal_transfer_tail(tail)
