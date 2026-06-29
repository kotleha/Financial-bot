import re

MIN_BANK_MERCHANT_KEY_LENGTH = 3


def normalize_bank_merchant_key(value: str | None) -> str:
    normalized = re.sub(r"[^0-9a-zа-яё]+", " ", (value or "").lower())
    normalized = " ".join(normalized.split())
    if len(normalized) < MIN_BANK_MERCHANT_KEY_LENGTH:
        return ""
    return normalized
