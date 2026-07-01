import re
from dataclasses import dataclass

from financial_bot.app.domain.money import AMOUNT_VALUE_PATTERN
from financial_bot.app.domain.types import BankEventBank


@dataclass(frozen=True, slots=True)
class BankSmsOperationMarker:
    code: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class BankSmsProfile:
    bank: BankEventBank
    sender_aliases: tuple[str, ...]
    text_prefixes: tuple[str, ...]
    instrument_pattern: re.Pattern[str]
    balance_marker_pattern: re.Pattern[str]
    operation_markers: tuple[BankSmsOperationMarker, ...]


SECURITY_MARKER_RE = re.compile(
    r"\bкод\b|\bпароль\b|\b3d-?s\b|\b3ds\b|подтвердите\s+электронные\s+документы",
    re.IGNORECASE,
)
SHAPE_AMOUNT_RE = re.compile(
    rf"{AMOUNT_VALUE_PATTERN}\s*(?:₽|руб\.?|р\.?|RUB)",
    re.IGNORECASE,
)
SHAPE_BALANCE_MARKER_RE = re.compile(r"\b(?:Баланс|Доступно)\b", re.IGNORECASE)
SHAPE_INSTRUMENT_MARKER_RE = re.compile(
    r"Карта\s*\*(?:\d+|<redacted>)|"
    r"Сч[её]т\s*\*(?:\d+|<redacted>)|"
    r"Сч[её]т\s+карты\s+MIR-(?:\d+|<redacted>)|"
    r"СЧ[ЕЁ]Т(?:\d+|<redacted>)|"
    r"сч[её]т\s+RUB",
    re.IGNORECASE,
)
VTB_INSTRUMENT_MARKER_RE = re.compile(r"(?:Карта|Сч[её]т)\s*\*\d+", re.IGNORECASE)

COMMON_OPERATION_MARKERS: tuple[BankSmsOperationMarker, ...] = (
    BankSmsOperationMarker("refund", re.compile(r"\bВозврат(?:\s+покупки)?\b", re.IGNORECASE)),
    BankSmsOperationMarker("purchase", re.compile(r"\bПокупка\b", re.IGNORECASE)),
    BankSmsOperationMarker("payment", re.compile(r"\bОплата\b", re.IGNORECASE)),
    BankSmsOperationMarker("debit", re.compile(r"\bСписание\b", re.IGNORECASE)),
    BankSmsOperationMarker("income", re.compile(r"\bПоступление\b", re.IGNORECASE)),
    BankSmsOperationMarker("topup", re.compile(r"\bПополнение\b", re.IGNORECASE)),
    BankSmsOperationMarker("credit", re.compile(r"\bЗачисление\b", re.IGNORECASE)),
    BankSmsOperationMarker("transfer", re.compile(r"\bПеревод\b", re.IGNORECASE)),
)

SBER_PROFILE = BankSmsProfile(
    bank=BankEventBank.SBER,
    sender_aliases=("900",),
    text_prefixes=("СЧЁТ", "СЧЕТ", "Счёт карты", "Счет карты"),
    instrument_pattern=SHAPE_INSTRUMENT_MARKER_RE,
    balance_marker_pattern=SHAPE_BALANCE_MARKER_RE,
    operation_markers=COMMON_OPERATION_MARKERS,
)
VTB_PROFILE = BankSmsProfile(
    bank=BankEventBank.VTB,
    sender_aliases=("vtb", "втб"),
    text_prefixes=(),
    instrument_pattern=VTB_INSTRUMENT_MARKER_RE,
    balance_marker_pattern=SHAPE_BALANCE_MARKER_RE,
    operation_markers=COMMON_OPERATION_MARKERS,
)
TBANK_PROFILE = BankSmsProfile(
    bank=BankEventBank.TBANK,
    sender_aliases=("t-bank", "tbank", "т-банк", "тинькофф", "tinkoff"),
    text_prefixes=(
        "Оплата СБП, счет RUB.",
        "Оплата СБП счет RUB",
        "Пополнение, счет RUB.",
        "Пополнение счет RUB",
        "Перевод. Карта *",
        "Перевод Карта *",
    ),
    instrument_pattern=SHAPE_INSTRUMENT_MARKER_RE,
    balance_marker_pattern=SHAPE_BALANCE_MARKER_RE,
    operation_markers=COMMON_OPERATION_MARKERS,
)

BANK_SMS_PROFILES: tuple[BankSmsProfile, ...] = (SBER_PROFILE, VTB_PROFILE, TBANK_PROFILE)


def detect_bank_from_profiles(text: str, sender: str) -> BankEventBank:
    sender_normalized = sender.strip().lower()
    text_normalized = text.strip().casefold()
    if text_normalized.startswith(_casefold_prefixes(TBANK_PROFILE.text_prefixes)):
        return BankEventBank.TBANK
    if _starts_with_sber_prefix(text_normalized):
        return BankEventBank.SBER
    if VTB_PROFILE.instrument_pattern.search(text):
        return BankEventBank.VTB
    if sender_normalized in TBANK_PROFILE.sender_aliases:
        return BankEventBank.TBANK
    if sender_normalized in SBER_PROFILE.sender_aliases:
        return BankEventBank.SBER
    if sender_normalized in VTB_PROFILE.sender_aliases:
        return BankEventBank.VTB
    return BankEventBank.UNKNOWN


def _casefold_prefixes(prefixes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(prefix.casefold() for prefix in prefixes)


def _starts_with_sber_prefix(text: str) -> bool:
    return text.startswith(("счёт карты", "счет карты")) or bool(
        re.match(r"^сч[её]т\d+", text, flags=re.IGNORECASE)
    )
