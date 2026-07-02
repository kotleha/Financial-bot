import re
from dataclasses import dataclass

from financial_bot.app.domain.accounting_scope import consume_leading_scope
from financial_bot.app.domain.money import AMOUNT_VALUE_PATTERN, parse_amount_to_minor_units
from financial_bot.app.domain.types import TransactionScope

DEFAULT_INCOME_CATEGORY_CODE = "income_general"
FALLBACK_INCOME_CATEGORY_CODE = "income_other"

INCOME_INPUT_RE = re.compile(
    rf"^\s*\+?(?P<amount>{AMOUNT_VALUE_PATTERN})(?:\s*(?:₽|руб\.?|р\.?|rub))?"
    r"(?:\s+(?P<tail>.+))?\s*$",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
INCOME_CATEGORY_ALIASES: tuple[tuple[str, str], ...] = (
    ("возврат долга", "income_debt_return"),
    ("вернули долг", "income_debt_return"),
    ("долг вернули", "income_debt_return"),
    ("заработная плата", "income_salary"),
    ("зарплата", "income_salary"),
    ("зп", "income_salary"),
    ("аванс", "income_advance"),
    ("премия", "income_bonus"),
    ("бонус", "income_bonus"),
    ("бизнес", "income_business"),
    ("проект", "income_business"),
    ("проекты", "income_business"),
    ("подработка", "income_business"),
    ("фриланс", "income_business"),
    ("доход", FALLBACK_INCOME_CATEGORY_CODE),
    ("поступление", FALLBACK_INCOME_CATEGORY_CODE),
    ("прочий доход", FALLBACK_INCOME_CATEGORY_CODE),
)


@dataclass(frozen=True, slots=True)
class ParsedIncomeInput:
    amount: int
    category_code: str
    comment: str
    scope: TransactionScope


def parse_income_input(text: str) -> ParsedIncomeInput:
    normalized_text = text.strip()
    if normalized_text.startswith("+"):
        normalized_text = normalized_text[1:].lstrip()

    parsed_scope, normalized_text = consume_leading_scope(normalized_text)
    scope = parsed_scope or TransactionScope.HOUSEHOLD

    match = INCOME_INPUT_RE.fullmatch(normalized_text)
    if match is None:
        msg = "Invalid income input"
        raise ValueError(msg)

    tail = (match.group("tail") or "").strip()
    return ParsedIncomeInput(
        amount=parse_amount_to_minor_units(match.group("amount")),
        category_code=_resolve_income_category_code(tail),
        comment=tail,
        scope=scope,
    )


def _resolve_income_category_code(text: str) -> str:
    if not text:
        return DEFAULT_INCOME_CATEGORY_CODE

    normalized = _normalize_words(text)
    for alias, category_code in INCOME_CATEGORY_ALIASES:
        if _normalize_words(alias) in normalized:
            return category_code
    return FALLBACK_INCOME_CATEGORY_CODE


def _normalize_words(text: str) -> str:
    words = [word.replace("ё", "е") for word in WORD_RE.findall(text.lower())]
    return f" {' '.join(words)} "
