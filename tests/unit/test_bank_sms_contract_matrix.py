from dataclasses import dataclass

import pytest
from financial_bot.app.domain.bank_sms import (
    BankSmsBank,
    BankSmsOperationKind,
    parse_bank_sms,
)
from financial_bot.app.domain.types import TransactionSource

# Synthetic parser contract fixtures. Do not replace these with real family SMS.
SELF_ALIASES = {"SELF PERSON", "FAMILY ACCOUNT"}


@dataclass(frozen=True, slots=True)
class BankSmsContractCase:
    name: str
    text: str
    sender: str
    bank: BankSmsBank
    operation_kind: BankSmsOperationKind
    amount: int | None
    source: TransactionSource
    requires_confirmation: bool
    suggested_category_code: str | None = None
    merchant: str = ""
    counterparty: str = ""


CONTRACT_CASES = (
    BankSmsContractCase(
        name="sber_card_purchase_with_operation_date",
        text="Счёт карты MIR-1111 01.07.26 02:05 Покупка 1700р SHABBA TEST Баланс: 133 812р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=170_000,
        source=TransactionSource.CARD,
        requires_confirmation=True,
        merchant="SHABBA TEST",
    ),
    BankSmsContractCase(
        name="sber_account_purchase",
        text="СЧЁТ1111 22:05 Покупка 1200р SHABBA TEST Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=120_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        merchant="SHABBA TEST",
    ),
    BankSmsContractCase(
        name="sber_account_payment_with_operation_date_fallback",
        text="СЧЁТ1111 01.07.26 22:05 Оплата 1200р SERVICE TEST Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=120_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        merchant="SERVICE TEST",
    ),
    BankSmsContractCase(
        name="sber_refund",
        text="Счёт карты MIR-1111 09:38 Возврат покупки по СБП 1794р CLOTHES TEST Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.REFUND,
        amount=179_400,
        source=TransactionSource.CARD,
        requires_confirmation=True,
        merchant="CLOTHES TEST",
    ),
    BankSmsContractCase(
        name="sber_refund_with_operation_date_fallback",
        text="Счёт карты MIR-1111 01.07.26 09:38 Возврат покупки 1794р CLOTHES TEST Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.REFUND,
        amount=179_400,
        source=TransactionSource.CARD,
        requires_confirmation=True,
        merchant="CLOTHES TEST",
    ),
    BankSmsContractCase(
        name="sber_external_income",
        text="СЧЁТ1111 15:49 Перевод по СБП из Т-Банк +10000р от EXTERNAL PERSON Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.INCOME,
        amount=1_000_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="sber_incoming_sbp_with_operation_date_fallback",
        text=(
            "СЧЁТ1111 01.07.26 15:49 Перевод по СБП из Т-Банк +10000р "
            "от EXTERNAL PERSON Баланс: 999р"
        ),
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.INCOME,
        amount=1_000_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="sber_self_transfer",
        text="СЧЁТ1111 10:26 перевод 10р FAMILY ACCOUNT Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.INTERNAL_TRANSFER,
        amount=1_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        suggested_category_code="internal_transfer",
        counterparty="FAMILY ACCOUNT",
    ),
    BankSmsContractCase(
        name="sber_outgoing_self_transfer_with_operation_date_fallback",
        text="СЧЁТ1111 01.07.26 10:26 перевод 10р FAMILY ACCOUNT Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.INTERNAL_TRANSFER,
        amount=1_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        suggested_category_code="internal_transfer",
        counterparty="FAMILY ACCOUNT",
    ),
    BankSmsContractCase(
        name="sber_credit_with_operation_date_fallback",
        text="СЧЁТ1111 01.07.26 05:37 Зачисление 1471,20р Баланс: 999р",
        sender="900",
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.INCOME,
        amount=147_120,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
    ),
    BankSmsContractCase(
        name="vtb_card_payment",
        text="Оплата 1234,56р Карта*1111 GAZPROMNEFT AZS Баланс 99999.99р 10:20",
        sender="VTB",
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=123_456,
        source=TransactionSource.CARD,
        requires_confirmation=True,
        suggested_category_code="auto",
        merchant="GAZPROMNEFT AZS",
    ),
    BankSmsContractCase(
        name="vtb_account_payment",
        text="Оплата 50р Счет *1111 GAZPROMNEFT AZS Баланс 99999.99р 10:20",
        sender="VTB",
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=5_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        suggested_category_code="auto",
        merchant="GAZPROMNEFT AZS",
    ),
    BankSmsContractCase(
        name="vtb_payment_with_colon_balance_fallback",
        text="Оплата 123р Карта *1111 TEST SHOP Баланс: 999р 10:20",
        sender="VTB",
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=12_300,
        source=TransactionSource.CARD,
        requires_confirmation=True,
        merchant="TEST SHOP",
    ),
    BankSmsContractCase(
        name="vtb_external_outgoing_debit",
        text="Списание 500р Счет *1111 EXTERNAL PERSON Баланс 999р 20:53",
        sender="VTB",
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=50_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        suggested_category_code="help_reserve",
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="vtb_outgoing_self_with_colon_balance_fallback",
        text="Списание 16910р Счет *1111 SELF PERSON Баланс: 999р 20:53",
        sender="VTB",
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.INTERNAL_TRANSFER,
        amount=1_691_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        suggested_category_code="internal_transfer",
        counterparty="SELF PERSON",
    ),
    BankSmsContractCase(
        name="vtb_external_income",
        text="Поступление 100р Счет *1111 от EXTERNAL PERSON Баланс 999р 10:20",
        sender="VTB",
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.INCOME,
        amount=10_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="vtb_incoming_with_colon_balance_fallback",
        text="Поступление 100р Счет *1111 от EXTERNAL PERSON Баланс: 999р 10:20",
        sender="VTB",
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.INCOME,
        amount=10_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="tbank_sbp_payment",
        text="Оплата СБП, счет RUB. 1855 RUB. RESTORAN TEST Доступно 26638,34 RUB",
        sender="T-Bank",
        bank=BankSmsBank.TBANK,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=185_500,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        suggested_category_code="restaurants_cafes",
        merchant="RESTORAN TEST",
    ),
    BankSmsContractCase(
        name="tbank_sbp_payment_relaxed_punctuation_fallback",
        text="Оплата СБП счет RUB 1855 RUB RESTORAN TEST Доступно 26638,34 RUB",
        sender="T-Bank",
        bank=BankSmsBank.TBANK,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=185_500,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        suggested_category_code="restaurants_cafes",
        merchant="RESTORAN TEST",
    ),
    BankSmsContractCase(
        name="tbank_topup_income",
        text="Пополнение, счет RUB. 1400 RUB. EXTERNAL PERSON Доступно 4532,34 RUB",
        sender="T-Bank",
        bank=BankSmsBank.TBANK,
        operation_kind=BankSmsOperationKind.INCOME,
        amount=140_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="tbank_topup_relaxed_punctuation_fallback",
        text="Пополнение счет RUB 1400 RUB EXTERNAL PERSON Доступно 4532,34 RUB",
        sender="T-Bank",
        bank=BankSmsBank.TBANK,
        operation_kind=BankSmsOperationKind.INCOME,
        amount=140_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=False,
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="tbank_external_card_transfer",
        text="Перевод. Карта *1111. 1250 RUB. EXTERNAL PERSON Баланс 189,44 RUB",
        sender="T-Bank",
        bank=BankSmsBank.TBANK,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=125_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        suggested_category_code="help_reserve",
        counterparty="EXTERNAL PERSON",
    ),
    BankSmsContractCase(
        name="tbank_card_transfer_relaxed_punctuation_fallback",
        text="Перевод Карта *1111 1250 RUB EXTERNAL PERSON Баланс 189,44 RUB",
        sender="T-Bank",
        bank=BankSmsBank.TBANK,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=125_000,
        source=TransactionSource.TRANSFER,
        requires_confirmation=True,
        suggested_category_code="help_reserve",
        counterparty="EXTERNAL PERSON",
    ),
)


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=[case.name for case in CONTRACT_CASES])
def test_bank_sms_contract_matrix(case: BankSmsContractCase) -> None:
    parsed = parse_bank_sms(
        case.text,
        sender=case.sender,
        self_counterparty_aliases=SELF_ALIASES,
    )

    assert parsed.bank == case.bank
    assert parsed.operation_kind == case.operation_kind
    assert parsed.amount == case.amount
    assert parsed.source == case.source
    assert parsed.requires_confirmation is case.requires_confirmation
    assert parsed.suggested_category_code == case.suggested_category_code
    assert parsed.merchant == case.merchant
    assert parsed.counterparty == case.counterparty
    assert parsed.creates_expense_candidate is (
        case.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE
    )


@pytest.mark.parametrize(
    ("text", "sender", "sensitive_value"),
    [
        (
            "СЧЁТ1111 01.07.26 10:26 перевод 10р FAMILY ACCOUNT Баланс: 999р",
            "900",
            "FAMILY ACCOUNT",
        ),
        (
            "Списание 16910р Счет *1111 SELF PERSON Баланс: 999р 20:53",
            "VTB",
            "SELF PERSON",
        ),
        (
            "Пополнение счет RUB 1400 RUB EXTERNAL PERSON Доступно 4532,34 RUB",
            "T-Bank",
            "EXTERNAL PERSON",
        ),
        (
            "Перевод Карта *1111 1250 RUB EXTERNAL PERSON Баланс 189,44 RUB",
            "T-Bank",
            "EXTERNAL PERSON",
        ),
    ],
)
def test_fallback_counterparties_are_redacted(
    text: str,
    sender: str,
    sensitive_value: str,
) -> None:
    parsed = parse_bank_sms(
        text,
        sender=sender,
        self_counterparty_aliases=SELF_ALIASES,
    )

    assert sensitive_value not in parsed.redacted_text
    assert "<counterparty>" in parsed.redacted_text


@pytest.mark.parametrize(
    ("text", "sender"),
    [
        ("Никому не сообщайте этот код для подтверждения: 123456. ВТБ", "VTB"),
        ("Для оплаты в TEST SHOP 2539.00 RUB Карта *1111; 3Ds код: 6485", "VTB"),
        ("Подтвердите электронные документы: код подтверждения 123456. Банк", "VTB"),
        ("Никому не говорите код 9366! Вы платите: Покупка, 8917.00 RUB", "T-Bank"),
        ("Одобрили кредитку с лимитом 250000 р. Получить: https://example.invalid", "T-Bank"),
        ("Возвращайтесь в ВТБ! До 14% годовых по вкладу: https://example.invalid", "VTB"),
    ],
)
def test_security_and_marketing_messages_do_not_create_expenses(text: str, sender: str) -> None:
    parsed = parse_bank_sms(text, sender=sender)

    assert parsed.operation_kind == BankSmsOperationKind.IGNORED
    assert parsed.amount is None
    assert not parsed.creates_expense_candidate
    assert not parsed.requires_confirmation


@pytest.mark.parametrize(
    ("text", "sender", "expected_bank"),
    [
        ("Баланс: 9999р", "900", BankSmsBank.SBER),
        ("Доступно 26638,34 RUB", "T-Bank", BankSmsBank.TBANK),
        ("Счет карты MIR-1111 Баланс: 1000р", "900", BankSmsBank.SBER),
        ("Счет *1111 Баланс 999р", "VTB", BankSmsBank.VTB),
    ],
)
def test_balance_only_messages_stay_unknown(
    text: str,
    sender: str,
    expected_bank: BankSmsBank,
) -> None:
    parsed = parse_bank_sms(text, sender=sender)

    assert parsed.bank == expected_bank
    assert parsed.operation_kind == BankSmsOperationKind.UNKNOWN
    assert parsed.amount is None
    assert not parsed.creates_expense_candidate
