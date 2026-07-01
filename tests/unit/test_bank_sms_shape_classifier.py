import pytest
from financial_bot.app.domain.bank_sms import BankSmsBank, classify_bank_sms_shape


@pytest.mark.parametrize(
    ("text", "sender", "expected_bank", "expected_markers"),
    [
        (
            "Счёт карты MIR-1111 01.07.26 02:05 Покупка 1700р SHABBA TEST Баланс: 133 812р",
            "900",
            BankSmsBank.SBER,
            ("purchase",),
        ),
        (
            "Оплата 1234,56р Карта*1111 GAZPROMNEFT AZS Баланс 99999.99р 10:20",
            "VTB",
            BankSmsBank.VTB,
            ("payment",),
        ),
        (
            "Оплата СБП, счет RUB. 1855 RUB. RESTORAN TEST Доступно 26638,34 RUB",
            "T-Bank",
            BankSmsBank.TBANK,
            ("payment",),
        ),
    ],
)
def test_shape_classifier_detects_safe_operation_shape(
    text: str,
    sender: str,
    expected_bank: BankSmsBank,
    expected_markers: tuple[str, ...],
) -> None:
    shape = classify_bank_sms_shape(text, sender=sender)

    assert shape.bank == expected_bank
    assert shape.operation_markers == expected_markers
    assert shape.amount_count == 2
    assert shape.has_balance_marker
    assert shape.has_instrument_marker
    assert not shape.is_ignored
    assert not shape.has_security_marker
    assert shape.has_minimum_operation_shape


def test_shape_classifier_marks_security_message_ignored_without_sensitive_payload() -> None:
    shape = classify_bank_sms_shape(
        "Никому не говорите код 9366! Вы платите: Покупка, 8917.00 RUB",
        sender="T-Bank",
    )

    assert shape.bank == BankSmsBank.TBANK
    assert shape.is_ignored
    assert shape.ignored_reason == "ignored_non_transaction_message"
    assert shape.has_security_marker
    assert shape.operation_markers == ("purchase",)
    assert shape.amount_count == 1
    assert not shape.has_minimum_operation_shape


@pytest.mark.parametrize(
    ("text", "sender", "expected_bank"),
    [
        ("Баланс: 9999р", "900", BankSmsBank.SBER),
        ("Доступно 26638,34 RUB", "T-Bank", BankSmsBank.TBANK),
        ("Счет *1111 Баланс 999р", "VTB", BankSmsBank.VTB),
    ],
)
def test_shape_classifier_keeps_balance_only_messages_out_of_operation_shape(
    text: str,
    sender: str,
    expected_bank: BankSmsBank,
) -> None:
    shape = classify_bank_sms_shape(text, sender=sender)

    assert shape.bank == expected_bank
    assert not shape.operation_markers
    assert shape.amount_count == 1
    assert shape.has_balance_marker
    assert not shape.is_ignored
    assert not shape.has_minimum_operation_shape
