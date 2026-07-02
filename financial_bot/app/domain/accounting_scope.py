import re

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
    "салон": TransactionScope.SALON,
}
_LEADING_TOKEN_RE = re.compile(r"^\s*(?P<token>[a-zа-яё]+)\b", re.IGNORECASE)


def scope_label(scope: TransactionScope | str | None) -> str:
    if scope is None:
        return SCOPE_LABELS[TransactionScope.HOUSEHOLD.value]
    value = scope.value if isinstance(scope, TransactionScope) else scope
    return SCOPE_LABELS.get(value, value)


def consume_leading_scope(text: str) -> tuple[TransactionScope | None, str]:
    match = _LEADING_TOKEN_RE.match(text)
    if match is None:
        return None, text

    token = match.group("token").lower().replace("ё", "е")
    scope = SCOPE_ALIASES.get(token)
    if scope is None:
        return None, text
    return scope, text[match.end() :].lstrip()
