from financial_bot.app.domain.accounting_scope import extract_scope_filter, scope_filter_label
from financial_bot.app.domain.types import TransactionScope


def test_extract_scope_filter_removes_first_scope_token() -> None:
    tokens, scope = extract_scope_filter(["month", "salon"])

    assert tokens == ["month"]
    assert scope == TransactionScope.SALON


def test_extract_scope_filter_supports_leading_scope_and_all_alias() -> None:
    tokens, scope = extract_scope_filter(["дом", "неделя"])
    all_tokens, all_scope = extract_scope_filter(["все", "месяц"])

    assert tokens == ["неделя"]
    assert scope == TransactionScope.HOUSEHOLD
    assert all_tokens == ["месяц"]
    assert all_scope is None
    assert scope_filter_label(all_scope) == "Все"
