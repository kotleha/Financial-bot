import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class AmountParseError(ValueError):
    """Raised when a user message cannot be parsed as a money amount."""


AMOUNT_VALUE_PATTERN = r"(?:\d+|\d{1,3}(?:[ \u00a0]\d{3})+)(?:[,.]\d+)?"
AMOUNT_ONLY_RE = re.compile(
    rf"^\s*{AMOUNT_VALUE_PATTERN}(?:\s*(?:₽|руб\.?|р\.?))?\s*$",
    re.IGNORECASE,
)


def is_amount_only_text(text: str) -> bool:
    return bool(AMOUNT_ONLY_RE.fullmatch(text))


def parse_amount_to_minor_units(text: str, *, minor_units: int = 100) -> int:
    if not AMOUNT_ONLY_RE.fullmatch(text):
        msg = "Amount must be a number, optionally with valid thousands spaces and cents"
        raise AmountParseError(msg)

    cleaned = (
        text.strip()
        .lower()
        .replace("руб.", "")
        .replace("руб", "")
        .replace("р.", "")
        .replace("₽", "")
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    if not cleaned or cleaned.count(".") > 1:
        msg = "Amount must contain digits and at most one decimal separator"
        raise AmountParseError(msg)

    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        msg = f"Invalid amount: {text!r}"
        raise AmountParseError(msg) from exc

    if amount <= 0:
        msg = "Amount must be positive"
        raise AmountParseError(msg)

    minor_amount = (amount * minor_units).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor_amount)


def format_money_minor(amount_minor: int, currency: str = "RUB", *, minor_units: int = 100) -> str:
    whole_units = amount_minor // minor_units
    fractional_units = amount_minor % minor_units
    formatted_whole = f"{whole_units:,}".replace(",", " ")

    if currency == "RUB":
        if fractional_units == 0:
            return f"{formatted_whole} ₽"
        return f"{formatted_whole},{fractional_units:02d} ₽"

    amount = Decimal(amount_minor) / Decimal(minor_units)
    return f"{amount:,.2f} {currency}".replace(",", " ")


def round_minor_to_whole_units_minor(
    amount_minor: int | Decimal,
    *,
    minor_units: int = 100,
) -> int:
    rounded_major_units = (Decimal(amount_minor) / Decimal(minor_units)).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    return int(rounded_major_units) * minor_units
