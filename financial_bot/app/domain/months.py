MONTH_ALIASES = {
    "jan": 1,
    "january": 1,
    "янв": 1,
    "январь": 1,
    "фев": 2,
    "feb": 2,
    "february": 2,
    "февраль": 2,
    "mar": 3,
    "march": 3,
    "мар": 3,
    "март": 3,
    "apr": 4,
    "april": 4,
    "апр": 4,
    "апрель": 4,
    "may": 5,
    "май": 5,
    "jun": 6,
    "june": 6,
    "июн": 6,
    "июнь": 6,
    "jul": 7,
    "july": 7,
    "июл": 7,
    "июль": 7,
    "aug": 8,
    "august": 8,
    "авг": 8,
    "август": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "сен": 9,
    "сентябрь": 9,
    "oct": 10,
    "october": 10,
    "окт": 10,
    "октябрь": 10,
    "nov": 11,
    "november": 11,
    "ноя": 11,
    "ноябрь": 11,
    "dec": 12,
    "december": 12,
    "дек": 12,
    "декабрь": 12,
}


def parse_month_token(token: str) -> int:
    normalized = token.strip().lower().rstrip(".,")
    if normalized.isdigit():
        month = int(normalized)
        if 1 <= month <= 12:
            return month

    if normalized not in MONTH_ALIASES:
        msg = f"Unknown month: {token}"
        raise ValueError(msg)
    return MONTH_ALIASES[normalized]
