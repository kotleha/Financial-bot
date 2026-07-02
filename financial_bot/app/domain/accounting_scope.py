import re
from collections.abc import Sequence

from financial_bot.app.domain.types import TransactionScope

SCOPE_LABELS = {
    TransactionScope.HOUSEHOLD.value: "Дом",
    TransactionScope.SALON.value: "Салон",
}
SCOPE_ALIASES = {
    "дом": TransactionScope.HOUSEHOLD,
    "дома": TransactionScope.HOUSEHOLD,
    "личное": TransactionScope.HOUSEHOLD,
    "личный": TransactionScope.HOUSEHOLD,
    "семья": TransactionScope.HOUSEHOLD,
    "семейное": TransactionScope.HOUSEHOLD,
    "home": TransactionScope.HOUSEHOLD,
    "household": TransactionScope.HOUSEHOLD,
    "салон": TransactionScope.SALON,
    "salon": TransactionScope.SALON,
}
ALL_SCOPE_FILTER_ALIASES = {"all", "все", "всё", "общий", "общая", "общее"}
_LEADING_TOKEN_RE = re.compile(r"^\s*(?P<token>[a-zа-яё]+)\b", re.IGNORECASE)
_TOKEN_CLEANUP_RE = re.compile(r"^[^\wа-яё]+|[^\wа-яё]+$", re.IGNORECASE)


def scope_label(scope: TransactionScope | str | None) -> str:
    if scope is None:
        return SCOPE_LABELS[TransactionScope.HOUSEHOLD.value]
    value = scope.value if isinstance(scope, TransactionScope) else scope
    return SCOPE_LABELS.get(value, value)


def scope_filter_label(scope: TransactionScope | None) -> str:
    if scope is None:
        return "Все"
    return scope_label(scope)


def extract_scope_filter(tokens: Sequence[str]) -> tuple[list[str], TransactionScope | None]:
    rest: list[str] = []
    scope: TransactionScope | None = None
    found_scope_token = False
    for token in tokens:
        parsed_scope, is_scope_token = _parse_scope_filter_token(token)
        if is_scope_token and not found_scope_token:
            scope = parsed_scope
            found_scope_token = True
            continue
        rest.append(token)
    return rest, scope


def consume_leading_scope(text: str) -> tuple[TransactionScope | None, str]:
    match = _LEADING_TOKEN_RE.match(text)
    if match is None:
        return None, text

    token = match.group("token").lower().replace("ё", "е")
    scope = SCOPE_ALIASES.get(token)
    if scope is None:
        return None, text
    return scope, text[match.end() :].lstrip()


def _parse_scope_filter_token(token: str) -> tuple[TransactionScope | None, bool]:
    normalized = _normalize_scope_token(token)
    if normalized in ALL_SCOPE_FILTER_ALIASES:
        return None, True
    scope = SCOPE_ALIASES.get(normalized)
    return scope, scope is not None


def _normalize_scope_token(token: str) -> str:
    return _TOKEN_CLEANUP_RE.sub("", token.strip().lower().replace("ё", "е"))
