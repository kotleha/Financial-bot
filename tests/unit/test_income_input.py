import pytest
from financial_bot.app.domain.income_input import parse_income_input


@pytest.mark.parametrize(
    ("text", "amount", "category_code", "comment"),
    [
        ("100000 зарплата", 10_000_000, "income_salary", "зарплата"),
        ("25000,50 аванс июнь", 2_500_050, "income_advance", "аванс июнь"),
        ("15000.25 бонус", 1_500_025, "income_bonus", "бонус"),
        ("+42000 проект", 4_200_000, "income_business", "проект"),
        ("7000 возврат долга", 700_000, "income_debt_return", "возврат долга"),
        ("3000 непонятное поступление", 300_000, "income_other", "непонятное поступление"),
        ("5000", 500_000, "income_general", ""),
    ],
)
def test_parse_income_input(text: str, amount: int, category_code: str, comment: str) -> None:
    parsed = parse_income_input(text)

    assert parsed.amount == amount
    assert parsed.category_code == category_code
    assert parsed.comment == comment


def test_parse_income_input_rejects_text_without_amount() -> None:
    with pytest.raises(ValueError, match=r"^Invalid income input$"):
        parse_income_input("зарплата")
