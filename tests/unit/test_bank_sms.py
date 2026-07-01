from datetime import time

import pytest
from financial_bot.app.domain.bank_sms import (
    BankSmsBank,
    BankSmsOperationKind,
    parse_bank_sms,
)
from financial_bot.app.domain.types import TransactionSource

# All examples in this file are synthetic parser fixtures, not copied user SMS.
SELF_ALIASES = {"SELF PERSON", "FAMILY ACCOUNT"}


@pytest.mark.parametrize(
    ("text", "sender", "expected_bank", "expected_category", "expected_amount"),
    [
        (
            ("Оплата 1234,56р Карта*1111 GAZPROMNEFT AZS Баланс 99999.99р 10:20"),
            "VTB",
            BankSmsBank.VTB,
            "auto",
            123456,
        ),
        (
            ("Оплата 50р Счет *1111 GAZPROMNEFT AZS Баланс 99999.99р 10:20"),
            "VTB",
            BankSmsBank.VTB,
            "auto",
            5000,
        ),
        (
            "Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 999р",
            "900",
            BankSmsBank.SBER,
            "cosmetology_medicine",
            29000,
        ),
        (
            "Счёт карты MIR-1111 09:16 Покупка 4040р RESTORAN TEST Баланс: 999р",
            "900",
            BankSmsBank.SBER,
            "restaurants_cafes",
            404000,
        ),
        (
            "СЧЁТ1111 22:05 Покупка 1200р SHABBA TEST Баланс: 999р",
            "900",
            BankSmsBank.SBER,
            None,
            120000,
        ),
        (
            "Счёт карты MIR-1111 10:17 Покупка по СБП 7342р LEMAN TEST Баланс: 999р",
            "900",
            BankSmsBank.SBER,
            "home_land",
            734200,
        ),
        (
            "Оплата СБП, счет RUB. 1855 RUB. RESTORAN TEST Доступно 26638,34 RUB",
            "T-Bank",
            BankSmsBank.TBANK,
            "restaurants_cafes",
            185500,
        ),
    ],
)
def test_parse_expense_candidates_with_category_hints(
    text: str,
    sender: str,
    expected_bank: BankSmsBank,
    expected_category: str,
    expected_amount: int,
) -> None:
    parsed = parse_bank_sms(text, sender=sender, self_counterparty_aliases=SELF_ALIASES)

    assert parsed.bank == expected_bank
    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.amount == expected_amount
    assert parsed.suggested_category_code == expected_category
    assert parsed.requires_confirmation
    assert parsed.creates_expense_candidate


def test_sber_payment_with_commission_keeps_fee_separate() -> None:
    parsed = parse_bank_sms(
        ("Счёт карты MIR-1111 15:52 Оплата 10 000р Комиссия 100р TRANSCORP TEST Баланс: 999р"),
        sender="900",
    )

    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.amount == 1_000_000
    assert parsed.fee_amount == 10_000
    assert parsed.merchant == "TRANSCORP TEST"
    assert parsed.requires_confirmation


def test_sber_operation_amount_is_not_confused_with_balance() -> None:
    parsed = parse_bank_sms(
        "Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
        sender="900",
    )

    assert parsed.amount == 29_000


def test_sber_account_purchase_is_expense_candidate() -> None:
    parsed = parse_bank_sms(
        "СЧЁТ1111 22:05 Покупка 1200р SHABBA TEST Баланс: 999р",
        sender="900",
    )

    assert parsed.bank == BankSmsBank.SBER
    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.amount == 120_000
    assert parsed.merchant == "SHABBA TEST"
    assert parsed.source == TransactionSource.TRANSFER
    assert parsed.operation_time == time(22, 5)
    assert "СЧЁТ1111" not in parsed.redacted_text
    assert "Баланс: <redacted>" in parsed.redacted_text


def test_tbank_operation_amount_is_not_confused_with_available_balance() -> None:
    parsed = parse_bank_sms(
        "Оплата СБП, счет RUB. 50 RUB. TEST SHOP Доступно 5000,25 RUB",
        sender="T-Bank",
    )

    assert parsed.bank == BankSmsBank.TBANK
    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.amount == 5_000
    assert parsed.merchant == "TEST SHOP"


@pytest.mark.parametrize(
    ("text", "sender", "expected_time"),
    [
        (
            "Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
            "900",
            time(11, 9),
        ),
        (
            "Оплата 1234р Карта*1111 GAZPROMNEFT AZS Баланс 999р 10:20",
            "VTB",
            time(10, 20),
        ),
        (
            "Поступление 100р Счет *1111 от EXTERNAL PERSON Баланс 999р 10:20",
            "VTB",
            time(10, 20),
        ),
    ],
)
def test_parse_operation_time(text: str, sender: str, expected_time: time) -> None:
    parsed = parse_bank_sms(text, sender=sender)

    assert parsed.operation_time == expected_time


def test_invalid_operation_time_does_not_crash_parser() -> None:
    parsed = parse_bank_sms(
        "Счёт карты MIR-1111 99:99 Покупка 290р APTEKA TEST Баланс: 924.14р",
        sender="900",
    )

    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.operation_time is None


@pytest.mark.parametrize(
    "text",
    [
        "СЧЁТ1111 04:53 Зачисление зарплаты 1665.57р Баланс: 999р",
        "СЧЁТ1111 05:37 Зачисление аванса 1471,20р Баланс: 999р",
        "СЧЁТ1111 05:37 Зачисление 1471,20р Баланс: 999р",
        "СЧЁТ1111 15:49 Перевод по СБП из Т-Банк +10000р от EXTERNAL PERSON Баланс: 999р",
        "Поступление 100р Счет *1111 от EXTERNAL PERSON Баланс 999р 10:20",
        "Пополнение, счет RUB. 1400 RUB. EXTERNAL PERSON Доступно 4532,34 RUB",
    ],
)
def test_sber_income_like_events_do_not_create_expenses(text: str) -> None:
    if text.startswith("Пополнение"):
        sender = "T-Bank"
        expected_bank = BankSmsBank.TBANK
    elif text.startswith("Поступление"):
        sender = "VTB"
        expected_bank = BankSmsBank.VTB
    else:
        sender = "900"
        expected_bank = BankSmsBank.SBER

    parsed = parse_bank_sms(text, sender=sender, self_counterparty_aliases=SELF_ALIASES)

    assert parsed.bank == expected_bank
    assert parsed.operation_kind == BankSmsOperationKind.INCOME
    assert not parsed.creates_expense_candidate
    assert not parsed.requires_confirmation


def test_vtb_text_shape_overrides_hardcoded_sber_sender() -> None:
    parsed = parse_bank_sms(
        "Оплата 1234р Счет *1111 GAZPROMNEFT AZS Баланс 999р 10:20",
        sender="900",
    )

    assert parsed.bank == BankSmsBank.VTB
    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE


@pytest.mark.parametrize(
    ("text", "sender"),
    [
        ("Списание 16910р Счет*1111 SELF PERSON Баланс 999р 20:53", "VTB"),
        ("Списание 16910р Счет *1111 SELF PERSON Баланс 999р 20:53", "VTB"),
        (
            "СЧЁТ1111 10:15 Перевод по СБП из ВТБ +10р от SELF PERSON Баланс: 999р",
            "900",
        ),
        ("СЧЁТ1111 10:26 перевод 10р FAMILY ACCOUNT Баланс: 999р", "900"),
        (
            "Пополнение, счет RUB. 1000 RUB. SELF PERSON Доступно 9999,99 RUB",
            "T-Bank",
        ),
        (
            "Перевод. Карта *1111. 1000 RUB. SELF PERSON Баланс 9999,99 RUB",
            "T-Bank",
        ),
    ],
)
def test_self_counterparty_transfers_are_internal(text: str, sender: str) -> None:
    parsed = parse_bank_sms(text, sender=sender, self_counterparty_aliases=SELF_ALIASES)

    assert parsed.operation_kind == BankSmsOperationKind.INTERNAL_TRANSFER
    assert parsed.suggested_category_code == "internal_transfer"
    assert not parsed.creates_expense_candidate
    assert not parsed.requires_confirmation
    assert parsed.source == TransactionSource.TRANSFER


def test_tbank_external_card_transfer_requires_confirmation_as_help_reserve() -> None:
    parsed = parse_bank_sms(
        "Перевод. Карта *1111. 1250 RUB. EXTERNAL PERSON Баланс 189,44 RUB",
        sender="T-Bank",
        self_counterparty_aliases=SELF_ALIASES,
    )

    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.amount == 125_000
    assert parsed.counterparty == "EXTERNAL PERSON"
    assert parsed.suggested_category_code == "help_reserve"
    assert parsed.requires_confirmation


def test_vtb_external_outgoing_debit_requires_confirmation_as_help_reserve() -> None:
    parsed = parse_bank_sms(
        "Списание 500р Счет *1111 EXTERNAL PERSON Баланс 999р 20:53",
        sender="VTB",
        self_counterparty_aliases=SELF_ALIASES,
    )

    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.amount == 50_000
    assert parsed.counterparty == "EXTERNAL PERSON"
    assert parsed.suggested_category_code == "help_reserve"
    assert parsed.requires_confirmation


def test_vtb_adjusted_payment_is_marked_as_adjusted_amount() -> None:
    parsed = parse_bank_sms(
        "Оплата с учетом возврата 2623.03р Счет *1111 GAZPROMNEFT AZS Баланс 999р 18:29",
        sender="VTB",
    )

    assert parsed.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    assert parsed.amount == 262_303
    assert parsed.suggested_category_code == "auto"
    assert parsed.is_adjusted_amount


def test_sber_refund_does_not_create_expense() -> None:
    parsed = parse_bank_sms(
        "Счёт карты MIR-1111 09:38 Возврат покупки по СБП 1794р CLOTHES TEST Баланс: 999р",
        sender="900",
    )

    assert parsed.operation_kind == BankSmsOperationKind.REFUND
    assert parsed.amount == 179_400
    assert not parsed.creates_expense_candidate
    assert parsed.requires_confirmation


@pytest.mark.parametrize(
    ("text", "sender"),
    [
        ("Никому не сообщайте этот код для подтверждения: 123456. ВТБ", "VTB"),
        ("Никому не говорите код 9366! Вы платите: Покупка, 8917.00 RUB", "T-Bank"),
        ("Никому не говорите код 5763! Вы платите: Переводы, 5000.00 RUB", "T-Bank"),
        ("Для оплаты в TEST SHOP 2539.00 RUB Карта *1111; 3Ds код: 6485", "VTB"),
        ("Подключены уведомления об операциях: https://example.invalid", "900"),
        ("Одобрили кредитку с лимитом 250000 р. Получить: https://example.invalid", "T-Bank"),
    ],
)
def test_ignore_non_transaction_messages_and_redact_codes(text: str, sender: str) -> None:
    parsed = parse_bank_sms(text, sender=sender)

    assert parsed.operation_kind == BankSmsOperationKind.IGNORED
    assert parsed.ignore_reason == "ignored_non_transaction_message"
    assert not parsed.creates_expense_candidate
    assert not parsed.requires_confirmation
    assert parsed.redacted_text == f"<ignored_non_transaction_message:{parsed.bank.value}>"
    assert "http" not in parsed.redacted_text
    assert "8917" not in parsed.redacted_text
    assert "250000" not in parsed.redacted_text
    assert "123456" not in parsed.redacted_text
    assert "6485" not in parsed.redacted_text
    assert "9366" not in parsed.redacted_text
    assert "5763" not in parsed.redacted_text


def test_redacted_text_removes_balances_and_card_or_account_suffixes() -> None:
    parsed = parse_bank_sms(
        "Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
        sender="900",
    )

    assert "MIR-1111" not in parsed.redacted_text
    assert "924.14" not in parsed.redacted_text
    assert "MIR-<redacted>" in parsed.redacted_text
    assert "Баланс: <redacted>" in parsed.redacted_text


@pytest.mark.parametrize(
    ("text", "sender"),
    [
        ("Списание 16910р Счет*1111 SELF PERSON Баланс 999р 20:53", "VTB"),
        ("Списание 16910р Счет *1111 SELF PERSON Баланс 999р 20:53", "VTB"),
        (
            "СЧЁТ1111 10:15 Перевод по СБП из ВТБ +10р от SELF PERSON Баланс: 999р",
            "900",
        ),
        ("СЧЁТ1111 10:26 перевод 10р FAMILY ACCOUNT Баланс: 999р", "900"),
        (
            "Пополнение, счет RUB. 1400 RUB. SELF PERSON Доступно 4532,34 RUB",
            "T-Bank",
        ),
        (
            "Перевод. Карта *1111. 1000 RUB. FAMILY ACCOUNT Баланс 2657,34 RUB",
            "T-Bank",
        ),
    ],
)
def test_redacted_text_removes_transfer_counterparties(text: str, sender: str) -> None:
    parsed = parse_bank_sms(text, sender=sender)

    assert "SELF PERSON" not in parsed.redacted_text
    assert "FAMILY ACCOUNT" not in parsed.redacted_text
    assert "<counterparty>" in parsed.redacted_text


def test_tbank_redacted_text_removes_available_balance_and_card_suffix() -> None:
    parsed = parse_bank_sms(
        "Перевод. Карта *1111. 1000 RUB. EXTERNAL PERSON Баланс 2657,34 RUB",
        sender="T-Bank",
    )

    assert "1111" not in parsed.redacted_text
    assert "2657" not in parsed.redacted_text
    assert "EXTERNAL PERSON" not in parsed.redacted_text
    assert "Карта*<redacted>" in parsed.redacted_text
    assert "<counterparty>" in parsed.redacted_text


def test_vtb_redacted_text_removes_spaced_account_suffix() -> None:
    parsed = parse_bank_sms(
        "Поступление 100р Счет *1111 от EXTERNAL PERSON Баланс 999р 10:20",
        sender="VTB",
    )

    assert "1111" not in parsed.redacted_text
    assert "999" not in parsed.redacted_text
    assert "EXTERNAL PERSON" not in parsed.redacted_text
    assert "Счет*<redacted>" in parsed.redacted_text
    assert "<counterparty>" in parsed.redacted_text
