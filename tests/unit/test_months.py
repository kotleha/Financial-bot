import pytest
from financial_bot.app.domain.months import parse_month_token


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("may", 5),
        ("май", 5),
        ("06", 6),
        ("jun", 6),
        ("июнь", 6),
    ],
)
def test_parse_month_token(token: str, expected: int) -> None:
    assert parse_month_token(token) == expected


def test_parse_month_token_rejects_unknown_month() -> None:
    with pytest.raises(ValueError):
        parse_month_token("not-a-month")
