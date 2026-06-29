import re
from dataclasses import dataclass

from financial_bot.app.domain.money import AMOUNT_VALUE_PATTERN, parse_amount_to_minor_units
from financial_bot.app.domain.types import TransactionSource, UserRole

CATEGORY_NUMBER_PATTERN = r"(?:[1-9]|1[0-7]|99)"
CATEGORY_NUMBER_ONLY_RE = re.compile(rf"^\s*(?P<category>{CATEGORY_NUMBER_PATTERN})\s*$")
AMOUNT_WITH_CATEGORY_NUMBER_RE = re.compile(
    rf"^\s*(?P<amount>{AMOUNT_VALUE_PATTERN})(?:\s*(?:₽|руб\.?|р\.?))?\s+"
    rf"(?P<category>{CATEGORY_NUMBER_PATTERN})(?:\s+(?P<comment>.+))?\s*$",
    re.IGNORECASE,
)
FREE_TEXT_EXPENSE_RE = re.compile(
    r"^\s*(?:(?P<payer>м|муж|ж|жена)\s+)?"
    rf"(?P<amount>{AMOUNT_VALUE_PATTERN})(?:\s*(?:₽|руб\.?|р\.?))?"
    r"(?:\s+(?P<tail>.+))?\s*$",
    re.IGNORECASE,
)
SOURCE_ALIASES = {
    "наличные": TransactionSource.CASH,
    "наличка": TransactionSource.CASH,
    "cash": TransactionSource.CASH,
    "карта": TransactionSource.CARD,
    "картой": TransactionSource.CARD,
    "card": TransactionSource.CARD,
    "перевод": TransactionSource.TRANSFER,
    "перевел": TransactionSource.TRANSFER,
    "перевёл": TransactionSource.TRANSFER,
    "скинул": TransactionSource.TRANSFER,
    "скинула": TransactionSource.TRANSFER,
    "отправил": TransactionSource.TRANSFER,
    "отправила": TransactionSource.TRANSFER,
}
PAYER_ALIASES = {
    "м": UserRole.HUSBAND,
    "муж": UserRole.HUSBAND,
    "ж": UserRole.WIFE,
    "жена": UserRole.WIFE,
}
INTERNAL_TRANSFER_RECIPIENT_WORDS = {
    "жене",
    "жена",
    "супруге",
    "супруга",
    "мужу",
    "муж",
    "супругу",
    "супруг",
}
INTERNAL_TRANSFER_MARKER_WORDS = {
    "перевод",
    "перевел",
    "перевёл",
    "перевела",
    "перевожу",
    "перечислил",
    "перечислила",
    "отправил",
    "отправила",
    "скинул",
    "скинула",
    "кинул",
    "кинула",
}
WORD_RE = re.compile(r"[a-zа-яё]+", re.IGNORECASE)
TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
SELF_TRANSFER_EXACT_PHRASES = {
    ("себе",),
    ("сам", "себе"),
    ("сама", "себе"),
    ("самому", "себе"),
    ("самой", "себе"),
    ("самоперевод",),
}
INTERNAL_TRANSFER_EXACT_PHRASES = {
    ("между", "нами"),
    ("между", "собой"),
    ("между", "своими", "счетами"),
    ("внутренний", "перевод"),
}


@dataclass(frozen=True, slots=True)
class ParsedAmountCategoryNumber:
    amount: int
    category_sort_order: int
    comment: str = ""


@dataclass(frozen=True, slots=True)
class ParsedFreeTextExpense:
    amount: int
    tail: str
    source: TransactionSource
    payer_role: UserRole | None


def is_category_number_only(text: str) -> bool:
    return bool(CATEGORY_NUMBER_ONLY_RE.fullmatch(text))


def parse_category_number(text: str) -> int:
    match = CATEGORY_NUMBER_ONLY_RE.fullmatch(text)
    if match is None:
        msg = f"Invalid category number: {text!r}"
        raise ValueError(msg)
    return int(match.group("category"))


def parse_amount_with_category_number(text: str) -> ParsedAmountCategoryNumber:
    match = AMOUNT_WITH_CATEGORY_NUMBER_RE.fullmatch(text)
    if match is None:
        msg = f"Invalid amount/category input: {text!r}"
        raise ValueError(msg)
    return ParsedAmountCategoryNumber(
        amount=parse_amount_to_minor_units(match.group("amount")),
        category_sort_order=int(match.group("category")),
        comment=(match.group("comment") or "").strip(),
    )


def parse_free_text_expense(text: str) -> ParsedFreeTextExpense:
    match = FREE_TEXT_EXPENSE_RE.fullmatch(text)
    if match is None:
        msg = "Invalid free-text expense input"
        raise ValueError(msg)

    tail = (match.group("tail") or "").strip()
    payer_raw = match.group("payer")
    payer_role = PAYER_ALIASES.get(payer_raw.lower()) if payer_raw else None

    return ParsedFreeTextExpense(
        amount=parse_amount_to_minor_units(match.group("amount")),
        tail=tail,
        source=_detect_source(tail),
        payer_role=payer_role,
    )


def is_internal_transfer_tail(text: str) -> bool:
    words = tuple(WORD_RE.findall(_normalize_text(text)))
    if not words:
        return False
    word_set = set(words)

    if words in SELF_TRANSFER_EXACT_PHRASES:
        return True
    if words in INTERNAL_TRANSFER_EXACT_PHRASES:
        return True
    if "самоперевод" in word_set:
        return True
    if "себе" in word_set and bool(word_set & INTERNAL_TRANSFER_MARKER_WORDS):
        return True

    has_recipient = bool(word_set & INTERNAL_TRANSFER_RECIPIENT_WORDS)
    if not has_recipient:
        return False

    return len(words) == 1 or bool(word_set & INTERNAL_TRANSFER_MARKER_WORDS)


def _detect_source(text: str) -> TransactionSource:
    text_tokens = _tokenize_text(text)
    for alias, source in SOURCE_ALIASES.items():
        if _contains_token_phrase(text_tokens, _tokenize_text(alias)):
            return source
    return TransactionSource.UNKNOWN


def _normalize_text(text: str) -> str:
    return text.lower().replace("ё", "е")


def _tokenize_text(text: str) -> tuple[str, ...]:
    return tuple(TOKEN_RE.findall(_normalize_text(text)))


def _contains_token_phrase(text_tokens: tuple[str, ...], alias_tokens: tuple[str, ...]) -> bool:
    if not alias_tokens or len(alias_tokens) > len(text_tokens):
        return False
    alias_length = len(alias_tokens)
    return any(
        text_tokens[index : index + alias_length] == alias_tokens
        for index in range(len(text_tokens) - alias_length + 1)
    )
