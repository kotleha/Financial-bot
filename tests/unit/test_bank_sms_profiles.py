import pytest
from financial_bot.app.domain.bank_sms_profiles import detect_bank_from_profiles
from financial_bot.app.domain.types import BankEventBank


@pytest.mark.parametrize(
    ("text", "sender", "expected_bank"),
    [
        ("Оплата СБП, счет RUB. 100 RUB. TEST Доступно 999 RUB", "", BankEventBank.TBANK),
        ("Оплата СБП счет RUB 100 RUB TEST Доступно 999 RUB", "", BankEventBank.TBANK),
        ("Пополнение, счет RUB. 100 RUB. TEST Доступно 999 RUB", "", BankEventBank.TBANK),
        ("Пополнение счет RUB 100 RUB TEST Доступно 999 RUB", "", BankEventBank.TBANK),
        ("Перевод. Карта *1111. 100 RUB. TEST Баланс 999 RUB", "", BankEventBank.TBANK),
        ("Перевод Карта *1111 100 RUB TEST Баланс 999 RUB", "", BankEventBank.TBANK),
        ("СЧЁТ1111 22:05 Покупка 1200р TEST Баланс: 999р", "", BankEventBank.SBER),
        ("Счет карты MIR-1111 11:09 Покупка 290р TEST Баланс: 999р", "", BankEventBank.SBER),
        ("Оплата 100р Счет *1111 TEST Баланс 999р 10:20", "900", BankEventBank.VTB),
        ("Баланс: 999р", "900", BankEventBank.SBER),
        ("Доступно 999 RUB", "T-Bank", BankEventBank.TBANK),
        ("Баланс 999р", "VTB", BankEventBank.VTB),
        ("Нерелевантное сообщение", "", BankEventBank.UNKNOWN),
    ],
)
def test_detect_bank_from_profiles_matches_current_detection_contract(
    text: str,
    sender: str,
    expected_bank: BankEventBank,
) -> None:
    assert detect_bank_from_profiles(text, sender) == expected_bank
