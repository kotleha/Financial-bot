import re
from dataclasses import dataclass
from datetime import time

from financial_bot.app.domain.bank_sms_profiles import (
    COMMON_OPERATION_MARKERS,
    SECURITY_MARKER_RE,
    SHAPE_AMOUNT_RE,
    SHAPE_BALANCE_MARKER_RE,
    SHAPE_INSTRUMENT_MARKER_RE,
    detect_bank_from_profiles,
)
from financial_bot.app.domain.money import AMOUNT_VALUE_PATTERN, parse_amount_to_minor_units
from financial_bot.app.domain.types import (
    BankEventBank,
    BankEventOperationKind,
    TransactionSource,
)

BankSmsBank = BankEventBank
BankSmsOperationKind = BankEventOperationKind


@dataclass(frozen=True, slots=True)
class ParsedBankSms:
    bank: BankSmsBank
    operation_kind: BankSmsOperationKind
    amount: int | None = None
    fee_amount: int | None = None
    currency: str = "RUB"
    merchant: str = ""
    counterparty: str = ""
    source: TransactionSource = TransactionSource.UNKNOWN
    suggested_category_code: str | None = None
    requires_confirmation: bool = True
    redacted_text: str = ""
    ignore_reason: str = ""
    is_adjusted_amount: bool = False
    operation_time: time | None = None

    @property
    def creates_expense_candidate(self) -> bool:
        return self.operation_kind == BankSmsOperationKind.EXPENSE_CANDIDATE


@dataclass(frozen=True, slots=True)
class BankSmsShape:
    bank: BankSmsBank
    operation_markers: tuple[str, ...]
    amount_count: int
    has_balance_marker: bool
    has_instrument_marker: bool
    ignored_reason: str = ""
    has_security_marker: bool = False

    @property
    def is_ignored(self) -> bool:
        return bool(self.ignored_reason)

    @property
    def has_operation_marker(self) -> bool:
        return bool(self.operation_markers)

    @property
    def has_minimum_operation_shape(self) -> bool:
        return (
            not self.is_ignored
            and self.has_operation_marker
            and self.has_balance_marker
            and self.amount_count >= 2
        )


MONEY_RE = rf"(?P<amount>{AMOUNT_VALUE_PATTERN})\s*(?:₽|руб\.?|р\.?|RUB)"
FEE_RE = rf"(?P<fee>{AMOUNT_VALUE_PATTERN})\s*(?:₽|руб\.?|р\.?|RUB)"
TIME_RE = r"(?P<time>\d{2}:\d{2})"
SBER_OPTIONAL_OPERATION_DATE_RE = r"(?:\s+\d{2}\.\d{2}\.\d{2,4})?"
SBER_CARD_OPERATION_PREFIX_RE = (
    rf"^Сч[её]т\s+карты\s+MIR-\d+{SBER_OPTIONAL_OPERATION_DATE_RE}\s+{TIME_RE}\s+"
)
BALANCE_RE = rf"\s+Баланс:?\s+{AMOUNT_VALUE_PATTERN}\s*(?:₽|руб\.?|р\.?|RUB)"
VTB_BALANCE_RE = rf"\s+Баланс\s+{AMOUNT_VALUE_PATTERN}\s*(?:₽|руб\.?|р\.?|RUB)"
VTB_FALLBACK_BALANCE_RE = rf"\s+Баланс:?\s+{AMOUNT_VALUE_PATTERN}\s*(?:₽|руб\.?|р\.?|RUB)"
TBANK_AVAILABLE_RE = rf"\s+Доступно\s+{AMOUNT_VALUE_PATTERN}\s*RUB"
TBANK_BALANCE_RE = rf"\s+Баланс\s+{AMOUNT_VALUE_PATTERN}\s*RUB"
TBANK_AMOUNT_RE = rf"(?P<amount>{AMOUNT_VALUE_PATTERN})\s*RUB"
MERCHANT_RE = r"(?P<merchant>.+?)"
COUNTERPARTY_RE = r"(?P<counterparty>.+?)"
VTB_PAYMENT_INSTRUMENT_RE = r"(?P<instrument>Карта|Сч[её]т)\s*\*\d+"
VTB_ACCOUNT_MASK_RE = r"Сч[её]т\s*\*\d+"

IGNORE_PATTERNS = (
    re.compile(r"никому\s+не\s+сообщайте.*\bкод\b", re.IGNORECASE),
    re.compile(r"никому\s+не\s+говорите.*\bкод\b", re.IGNORECASE),
    re.compile(r"\b3d-?s\b.*\bкод\b|\b3ds\b.*\bкод\b", re.IGNORECASE),
    re.compile(r"для\s+оплаты\b.*\bкод\b", re.IGNORECASE),
    re.compile(r"подтвердите\s+электронные\s+документы", re.IGNORECASE),
    re.compile(r"подключены\s+уведомления", re.IGNORECASE),
    re.compile(r"возвращайтесь\s+в\s+втб", re.IGNORECASE),
    re.compile(r"\bкод\s+подтверждения\b", re.IGNORECASE),
    re.compile(r"\bодобрили\b.*\bлимит", re.IGNORECASE),
    re.compile(r"\bоткройте\s+счет\b.*\bподар", re.IGNORECASE),
    re.compile(r"\bвстреча\s+с\s+представителем\b", re.IGNORECASE),
)

VTB_ADJUSTED_PAYMENT_RE = re.compile(
    rf"^Оплата\s+с\s+учетом\s+возврата\s+{MONEY_RE}\s+"
    rf"{VTB_PAYMENT_INSTRUMENT_RE}\s+{MERCHANT_RE}{VTB_BALANCE_RE}\s+{TIME_RE}$",
    re.IGNORECASE,
)
VTB_CARD_PAYMENT_RE = re.compile(
    rf"^Оплата\s+{MONEY_RE}\s+{VTB_PAYMENT_INSTRUMENT_RE}\s+"
    rf"{MERCHANT_RE}{VTB_BALANCE_RE}\s+{TIME_RE}$",
    re.IGNORECASE,
)
VTB_OUTGOING_DEBIT_RE = re.compile(
    rf"^Списание\s+{MONEY_RE}\s+{VTB_ACCOUNT_MASK_RE}\s+"
    rf"{COUNTERPARTY_RE}{VTB_BALANCE_RE}\s+{TIME_RE}$",
    re.IGNORECASE,
)
VTB_INCOMING_CREDIT_RE = re.compile(
    rf"^Поступление\s+{MONEY_RE}\s+{VTB_ACCOUNT_MASK_RE}\s+от\s+{COUNTERPARTY_RE}"
    rf"{VTB_BALANCE_RE}\s+{TIME_RE}$",
    re.IGNORECASE,
)
VTB_SAFE_OUTGOING_DEBIT_FALLBACK_RE = re.compile(
    rf"^Списание\s+{MONEY_RE}\s+{VTB_ACCOUNT_MASK_RE}\s+"
    rf"{COUNTERPARTY_RE}{VTB_FALLBACK_BALANCE_RE}(?:\s+{TIME_RE})?$",
    re.IGNORECASE,
)
VTB_SAFE_INCOMING_CREDIT_FALLBACK_RE = re.compile(
    rf"^Поступление\s+{MONEY_RE}\s+{VTB_ACCOUNT_MASK_RE}\s+от\s+{COUNTERPARTY_RE}"
    rf"{VTB_FALLBACK_BALANCE_RE}(?:\s+{TIME_RE})?$",
    re.IGNORECASE,
)

SBER_CARD_REFUND_RE = re.compile(
    rf"{SBER_CARD_OPERATION_PREFIX_RE}Возврат\s+покупки\s+по\s+СБП\s+"
    rf"{MONEY_RE}\s+{MERCHANT_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_SAFE_REFUND_FALLBACK_RE = re.compile(
    rf"^(?P<instrument>Сч[её]т\s+карты\s+MIR-\d+|СЧ[ЕЁ]Т\d+)"
    rf"{SBER_OPTIONAL_OPERATION_DATE_RE}\s+{TIME_RE}\s+"
    rf"Возврат\s+покупки(?P<sbp>\s+по\s+СБП)?\s+{MONEY_RE}\s+"
    rf"{MERCHANT_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_CARD_SBP_PURCHASE_RE = re.compile(
    rf"{SBER_CARD_OPERATION_PREFIX_RE}Покупка\s+по\s+СБП\s+"
    rf"{MONEY_RE}\s+{MERCHANT_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_CARD_PURCHASE_RE = re.compile(
    rf"{SBER_CARD_OPERATION_PREFIX_RE}Покупка\s+"
    rf"{MONEY_RE}\s+{MERCHANT_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_CARD_PAYMENT_RE = re.compile(
    rf"{SBER_CARD_OPERATION_PREFIX_RE}Оплата\s+{MONEY_RE}"
    rf"(?:\s+Комиссия\s+{FEE_RE})?(?:\s+{MERCHANT_RE})?{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_PURCHASE_RE = re.compile(
    rf"^(?P<instrument>Сч[её]т\s+карты\s+MIR-\d+|СЧ[ЕЁ]Т\d+)"
    rf"(?:\s+\d{{2}}\.\d{{2}}\.\d{{2,4}})?\s+{TIME_RE}\s+"
    rf"Покупка(?P<sbp>\s+по\s+СБП)?\s+{MONEY_RE}\s+{MERCHANT_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_INCOMING_SBP_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+\s+{TIME_RE}\s+Перевод\s+по\s+СБП\s+из\s+.+?\s+\+"
    rf"{MONEY_RE}\s+от\s+{COUNTERPARTY_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_SAFE_INCOMING_SBP_FALLBACK_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+{SBER_OPTIONAL_OPERATION_DATE_RE}\s+{TIME_RE}\s+"
    rf"Перевод\s+по\s+СБП\s+из\s+.+?\s+\+{MONEY_RE}\s+от\s+"
    rf"{COUNTERPARTY_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_OUTGOING_TRANSFER_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+\s+{TIME_RE}\s+перевод\s+{MONEY_RE}(?:\s+{COUNTERPARTY_RE})?"
    rf"{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_SAFE_OUTGOING_TRANSFER_FALLBACK_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+{SBER_OPTIONAL_OPERATION_DATE_RE}\s+{TIME_RE}\s+перевод\s+"
    rf"{MONEY_RE}(?:\s+{COUNTERPARTY_RE})?{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_SALARY_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+\s+{TIME_RE}\s+Зачисление\s+(?:зарплаты|аванса)\s+"
    rf"{MONEY_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_GENERIC_CREDIT_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+\s+{TIME_RE}\s+Зачисление\s+{MONEY_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_SAFE_CREDIT_FALLBACK_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+{SBER_OPTIONAL_OPERATION_DATE_RE}\s+{TIME_RE}\s+"
    rf"(?:Поступление|Пополнение|Зачисление)(?:\s+(?:зарплаты|аванса))?\s+"
    rf"{MONEY_RE}(?:\s+от\s+{COUNTERPARTY_RE})?{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_ACCOUNT_PAYMENT_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+\s+{TIME_RE}\s+Оплата\s+{MONEY_RE}(?:\s+{MERCHANT_RE})?"
    rf"{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_ACCOUNT_PURCHASE_RE = re.compile(
    rf"^СЧ[ЕЁ]Т\d+\s+{TIME_RE}\s+Покупка\s+{MONEY_RE}\s+{MERCHANT_RE}{BALANCE_RE}$",
    re.IGNORECASE,
)
SBER_SAFE_EXPENSE_FALLBACK_RE = re.compile(
    rf"^(?P<instrument>Сч[её]т\s+карты\s+MIR-\d+|СЧ[ЕЁ]Т\d+)"
    rf"(?:\s+\d{{2}}\.\d{{2}}\.\d{{2,4}})?\s+{TIME_RE}\s+"
    rf"(?P<operation>Покупка|Оплата)(?P<sbp>\s+по\s+СБП)?\s+{MONEY_RE}"
    rf"(?:\s+{MERCHANT_RE})?{BALANCE_RE}$",
    re.IGNORECASE,
)
VTB_SAFE_PAYMENT_FALLBACK_RE = re.compile(
    rf"^Оплата(?P<adjusted>\s+с\s+учетом\s+возврата)?\s+{MONEY_RE}\s+"
    rf"{VTB_PAYMENT_INSTRUMENT_RE}\s+{MERCHANT_RE}{VTB_FALLBACK_BALANCE_RE}"
    rf"(?:\s+{TIME_RE})?$",
    re.IGNORECASE,
)
TBANK_SBP_PAYMENT_RE = re.compile(
    rf"^Оплата\s+СБП,\s+сч[её]т\s+RUB\.\s+{TBANK_AMOUNT_RE}\.\s+"
    rf"{MERCHANT_RE}{TBANK_AVAILABLE_RE}$",
    re.IGNORECASE,
)
TBANK_TOPUP_RE = re.compile(
    rf"^Пополнение,\s+сч[её]т\s+RUB\.\s+{TBANK_AMOUNT_RE}\.\s+"
    rf"{COUNTERPARTY_RE}{TBANK_AVAILABLE_RE}$",
    re.IGNORECASE,
)
TBANK_SAFE_TOPUP_FALLBACK_RE = re.compile(
    rf"^Пополнение[,]?\s+сч[её]т\s+RUB\.?\s+{TBANK_AMOUNT_RE}\.?\s+"
    rf"{COUNTERPARTY_RE}{TBANK_AVAILABLE_RE}$",
    re.IGNORECASE,
)
TBANK_CARD_TRANSFER_RE = re.compile(
    rf"^Перевод\.\s+Карта\s+\*\d+\.\s+{TBANK_AMOUNT_RE}\.\s+"
    rf"{COUNTERPARTY_RE}{TBANK_BALANCE_RE}$",
    re.IGNORECASE,
)
TBANK_SAFE_CARD_TRANSFER_FALLBACK_RE = re.compile(
    rf"^Перевод\.?\s+Карта\s+\*\d+\.?\s+{TBANK_AMOUNT_RE}\.?\s+"
    rf"{COUNTERPARTY_RE}{TBANK_BALANCE_RE}$",
    re.IGNORECASE,
)
TBANK_SAFE_PAYMENT_FALLBACK_RE = re.compile(
    rf"^Оплата(?:\s+СБП)?[,]?\s+сч[её]т\s+RUB\.?\s+{TBANK_AMOUNT_RE}\.?\s+"
    rf"{MERCHANT_RE}{TBANK_AVAILABLE_RE}$",
    re.IGNORECASE,
)

CATEGORY_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("GAZPROMNEFT", "АЗС", " AZS", "BENZIN", "ТОПЛИВО"), "auto"),
    (("BEELINE", "БИЛАЙН", "MTS", "МТС", "MEGAFON", "МЕГАФОН"), "subscriptions_communications"),
    (("СБЕРПРАЙМ", "SBERPRIME"), "subscriptions_communications"),
    (("APTEKA", "АПТЕКА", "PHARM", "ФАРМ"), "cosmetology_medicine"),
    (("RESTORAN", "РЕСТОРАН", "CAFE", "КАФЕ", "SBERCHAEVYE"), "restaurants_cafes"),
    (("SUPERMARKET", "СУПЕРМАРКЕТ", "GROCERY", "ПРОДУКТ"), "groceries"),
    (("LEMAN", "ЛЕМАН", "LEROY", "ЛЕРУА", "СТРОЙ"), "home_land"),
)


def parse_bank_sms(
    text: str,
    *,
    sender: str = "",
    self_counterparty_aliases: tuple[str, ...] | set[str] | frozenset[str] = (),
) -> ParsedBankSms:
    normalized_text = _normalize_text(text)
    redacted_text = redact_bank_sms_text(normalized_text)
    bank = _detect_bank(normalized_text, sender)

    ignore_reason = _ignore_reason(normalized_text)
    if ignore_reason:
        return ParsedBankSms(
            bank=bank,
            operation_kind=BankSmsOperationKind.IGNORED,
            requires_confirmation=False,
            redacted_text=_ignored_redacted_text(bank, ignore_reason),
            ignore_reason=ignore_reason,
        )

    self_aliases = {_normalize_counterparty(alias) for alias in self_counterparty_aliases}

    if bank == BankSmsBank.VTB:
        return _parse_vtb(normalized_text, redacted_text, self_aliases)
    if bank == BankSmsBank.SBER:
        return _parse_sber(normalized_text, redacted_text, self_aliases)
    if bank == BankSmsBank.TBANK:
        return _parse_tbank(normalized_text, redacted_text, self_aliases)

    return ParsedBankSms(
        bank=BankSmsBank.UNKNOWN,
        operation_kind=BankSmsOperationKind.UNKNOWN,
        redacted_text=redacted_text,
        ignore_reason="unknown_format",
    )


def classify_bank_sms_shape(text: str, *, sender: str = "") -> BankSmsShape:
    normalized_text = _normalize_text(text)
    ignored_reason = _ignore_reason(normalized_text)
    return BankSmsShape(
        bank=_detect_bank(normalized_text, sender),
        operation_markers=tuple(
            marker.code
            for marker in COMMON_OPERATION_MARKERS
            if marker.pattern.search(normalized_text)
        ),
        amount_count=len(SHAPE_AMOUNT_RE.findall(normalized_text)),
        has_balance_marker=bool(SHAPE_BALANCE_MARKER_RE.search(normalized_text)),
        has_instrument_marker=bool(SHAPE_INSTRUMENT_MARKER_RE.search(normalized_text)),
        ignored_reason=ignored_reason,
        has_security_marker=bool(SECURITY_MARKER_RE.search(normalized_text)),
    )


def redact_bank_sms_text(text: str) -> str:
    redacted = _normalize_text(text)
    redacted = re.sub(
        rf"Баланс:?\s+{AMOUNT_VALUE_PATTERN}\s*(?:₽|руб\.?|р\.?|RUB)",
        "Баланс: <redacted>",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        rf"Доступно\s+{AMOUNT_VALUE_PATTERN}\s*RUB",
        "Доступно <redacted>",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(r"Карта\s*\*\d+", "Карта*<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"Сч[её]т\s*\*\d+", "Счет*<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(
        r"Сч[её]т\s+карты\s+MIR-\d+",
        "Счёт карты MIR-<redacted>",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(r"СЧ[ЕЁ]Т\d+", "СЧЁТ<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(
        rf"(Списание\s+{AMOUNT_VALUE_PATTERN}\s*(?:₽|руб\.?|р\.?)\s+"
        r"Счет\*<redacted>\s+).+?(\s+Баланс:?\s+<redacted>)",
        r"\1<counterparty>\2",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"(\sот\s+).+?(\s+Баланс:?\s+<redacted>)",
        r"\1<counterparty>\2",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        rf"(СЧЁТ<redacted>(?:\s+\d{{2}}\.\d{{2}}\.\d{{2,4}})?"
        rf"\s+\d{{2}}:\d{{2}}\s+перевод\s+{AMOUNT_VALUE_PATTERN}"
        r"\s*(?:₽|руб\.?|р\.?)?\s+).+?(\s+Баланс:?\s+<redacted>)",
        r"\1<counterparty>\2",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        rf"(Пополнение[,]?\s+сч[её]т\s+RUB\.?\s+{AMOUNT_VALUE_PATTERN}\s*RUB\.?\s+)"
        r".+?(\s+Доступно\s+<redacted>)",
        r"\1<counterparty>\2",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        rf"(Перевод\.?\s+Карта\*<redacted>\.?\s+{AMOUNT_VALUE_PATTERN}\s*RUB\.?\s+)"
        r".+?(\s+Баланс:?\s+<redacted>)",
        r"\1<counterparty>\2",
        redacted,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bкод\b|\bпароль\b", redacted, re.IGNORECASE):
        redacted = re.sub(r"\b\d{4,8}\b", "<code>", redacted)
    return redacted


def _parse_vtb(text: str, redacted_text: str, self_aliases: set[str]) -> ParsedBankSms:
    if match := VTB_ADJUSTED_PAYMENT_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.VTB,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=_vtb_payment_source(match.group("instrument")),
            redacted_text=redacted_text,
            is_adjusted_amount=True,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := VTB_CARD_PAYMENT_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.VTB,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=_vtb_payment_source(match.group("instrument")),
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := VTB_OUTGOING_DEBIT_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            return ParsedBankSms(
                bank=BankSmsBank.VTB,
                operation_kind=BankSmsOperationKind.INTERNAL_TRANSFER,
                amount=amount,
                counterparty=counterparty,
                source=TransactionSource.TRANSFER,
                suggested_category_code="internal_transfer",
                requires_confirmation=False,
                redacted_text=redacted_text,
                operation_time=_parse_operation_time(match.group("time")),
            )
        return ParsedBankSms(
            bank=BankSmsBank.VTB,
            operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code="help_reserve",
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := VTB_INCOMING_CREDIT_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
            requires_confirmation = False
        else:
            operation_kind = BankSmsOperationKind.INCOME
            category_code = None
            requires_confirmation = False
        return ParsedBankSms(
            bank=BankSmsBank.VTB,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=requires_confirmation,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := VTB_SAFE_OUTGOING_DEBIT_FALLBACK_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            return ParsedBankSms(
                bank=BankSmsBank.VTB,
                operation_kind=BankSmsOperationKind.INTERNAL_TRANSFER,
                amount=amount,
                counterparty=counterparty,
                source=TransactionSource.TRANSFER,
                suggested_category_code="internal_transfer",
                requires_confirmation=False,
                redacted_text=redacted_text,
                operation_time=_parse_operation_time(match.group("time")),
            )
        return ParsedBankSms(
            bank=BankSmsBank.VTB,
            operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code="help_reserve",
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := VTB_SAFE_INCOMING_CREDIT_FALLBACK_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
            requires_confirmation = False
        else:
            operation_kind = BankSmsOperationKind.INCOME
            category_code = None
            requires_confirmation = False
        return ParsedBankSms(
            bank=BankSmsBank.VTB,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=requires_confirmation,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := VTB_SAFE_PAYMENT_FALLBACK_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.VTB,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=_vtb_payment_source(match.group("instrument")),
            redacted_text=redacted_text,
            is_adjusted_amount=bool(match.group("adjusted")),
            operation_time=_parse_operation_time(match.group("time")),
        )

    return ParsedBankSms(
        bank=BankSmsBank.VTB,
        operation_kind=BankSmsOperationKind.UNKNOWN,
        redacted_text=redacted_text,
        ignore_reason="unsupported_vtb_format",
    )


def _parse_sber(text: str, redacted_text: str, self_aliases: set[str]) -> ParsedBankSms:
    if match := SBER_CARD_REFUND_RE.fullmatch(text):
        merchant = _clean_party(match.group("merchant"))
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=BankSmsOperationKind.REFUND,
            amount=_parse_amount(match.group("amount")),
            merchant=merchant,
            source=TransactionSource.CARD,
            suggested_category_code=_suggest_category_code(merchant),
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_SAFE_REFUND_FALLBACK_RE.fullmatch(text):
        merchant = _clean_party(match.group("merchant"))
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=BankSmsOperationKind.REFUND,
            amount=_parse_amount(match.group("amount")),
            merchant=merchant,
            source=_sber_purchase_source(
                instrument=match.group("instrument"),
                is_sbp=bool(match.group("sbp")),
            ),
            suggested_category_code=_suggest_category_code(merchant),
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_PURCHASE_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.SBER,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=_sber_purchase_source(
                instrument=match.group("instrument"),
                is_sbp=bool(match.group("sbp")),
            ),
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_CARD_SBP_PURCHASE_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.SBER,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=TransactionSource.TRANSFER,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_CARD_PURCHASE_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.SBER,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=TransactionSource.CARD,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_CARD_PAYMENT_RE.fullmatch(text):
        merchant = _clean_party(match.group("merchant") or "")
        return _expense_candidate(
            bank=BankSmsBank.SBER,
            amount_raw=match.group("amount"),
            merchant=merchant,
            source=TransactionSource.CARD,
            redacted_text=redacted_text,
            fee_amount=_parse_amount(match.group("fee")) if match.group("fee") else None,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_INCOMING_SBP_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            return ParsedBankSms(
                bank=BankSmsBank.SBER,
                operation_kind=BankSmsOperationKind.INTERNAL_TRANSFER,
                amount=amount,
                counterparty=counterparty,
                source=TransactionSource.TRANSFER,
                suggested_category_code="internal_transfer",
                requires_confirmation=False,
                redacted_text=redacted_text,
                operation_time=_parse_operation_time(match.group("time")),
            )
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=BankSmsOperationKind.INCOME,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            requires_confirmation=False,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_SAFE_INCOMING_SBP_FALLBACK_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            return ParsedBankSms(
                bank=BankSmsBank.SBER,
                operation_kind=BankSmsOperationKind.INTERNAL_TRANSFER,
                amount=amount,
                counterparty=counterparty,
                source=TransactionSource.TRANSFER,
                suggested_category_code="internal_transfer",
                requires_confirmation=False,
                redacted_text=redacted_text,
                operation_time=_parse_operation_time(match.group("time")),
            )
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=BankSmsOperationKind.INCOME,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            requires_confirmation=False,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_OUTGOING_TRANSFER_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty") or "")
        amount = _parse_amount(match.group("amount"))
        if counterparty and _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
            requires_confirmation = False
        else:
            operation_kind = BankSmsOperationKind.EXPENSE_CANDIDATE
            category_code = "help_reserve"
            requires_confirmation = True
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=requires_confirmation,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_SAFE_OUTGOING_TRANSFER_FALLBACK_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty") or "")
        amount = _parse_amount(match.group("amount"))
        if counterparty and _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
            requires_confirmation = False
        else:
            operation_kind = BankSmsOperationKind.EXPENSE_CANDIDATE
            category_code = "help_reserve"
            requires_confirmation = True
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=requires_confirmation,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_SALARY_RE.fullmatch(text):
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=BankSmsOperationKind.INCOME,
            amount=_parse_amount(match.group("amount")),
            source=TransactionSource.TRANSFER,
            requires_confirmation=False,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_GENERIC_CREDIT_RE.fullmatch(text):
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=BankSmsOperationKind.INCOME,
            amount=_parse_amount(match.group("amount")),
            source=TransactionSource.TRANSFER,
            requires_confirmation=False,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_SAFE_CREDIT_FALLBACK_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty") or "")
        amount = _parse_amount(match.group("amount"))
        if counterparty and _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
        else:
            operation_kind = BankSmsOperationKind.INCOME
            category_code = None
        return ParsedBankSms(
            bank=BankSmsBank.SBER,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=False,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_ACCOUNT_PAYMENT_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.SBER,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant") or ""),
            source=TransactionSource.TRANSFER,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_ACCOUNT_PURCHASE_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.SBER,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=TransactionSource.TRANSFER,
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    if match := SBER_SAFE_EXPENSE_FALLBACK_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.SBER,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant") or ""),
            source=_sber_purchase_source(
                instrument=match.group("instrument"),
                is_sbp=bool(match.group("sbp")),
            ),
            redacted_text=redacted_text,
            operation_time=_parse_operation_time(match.group("time")),
        )

    return ParsedBankSms(
        bank=BankSmsBank.SBER,
        operation_kind=BankSmsOperationKind.UNKNOWN,
        redacted_text=redacted_text,
        ignore_reason="unsupported_sber_format",
    )


def _parse_tbank(text: str, redacted_text: str, self_aliases: set[str]) -> ParsedBankSms:
    if match := TBANK_SBP_PAYMENT_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.TBANK,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=TransactionSource.TRANSFER,
            redacted_text=redacted_text,
        )

    if match := TBANK_TOPUP_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
        else:
            operation_kind = BankSmsOperationKind.INCOME
            category_code = None
        return ParsedBankSms(
            bank=BankSmsBank.TBANK,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=False,
            redacted_text=redacted_text,
        )

    if match := TBANK_SAFE_TOPUP_FALLBACK_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
        else:
            operation_kind = BankSmsOperationKind.INCOME
            category_code = None
        return ParsedBankSms(
            bank=BankSmsBank.TBANK,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=False,
            redacted_text=redacted_text,
        )

    if match := TBANK_CARD_TRANSFER_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
            requires_confirmation = False
        else:
            operation_kind = BankSmsOperationKind.EXPENSE_CANDIDATE
            category_code = "help_reserve"
            requires_confirmation = True
        return ParsedBankSms(
            bank=BankSmsBank.TBANK,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=requires_confirmation,
            redacted_text=redacted_text,
        )

    if match := TBANK_SAFE_CARD_TRANSFER_FALLBACK_RE.fullmatch(text):
        counterparty = _clean_party(match.group("counterparty"))
        amount = _parse_amount(match.group("amount"))
        if _is_self_counterparty(counterparty, self_aliases):
            operation_kind = BankSmsOperationKind.INTERNAL_TRANSFER
            category_code = "internal_transfer"
            requires_confirmation = False
        else:
            operation_kind = BankSmsOperationKind.EXPENSE_CANDIDATE
            category_code = "help_reserve"
            requires_confirmation = True
        return ParsedBankSms(
            bank=BankSmsBank.TBANK,
            operation_kind=operation_kind,
            amount=amount,
            counterparty=counterparty,
            source=TransactionSource.TRANSFER,
            suggested_category_code=category_code,
            requires_confirmation=requires_confirmation,
            redacted_text=redacted_text,
        )

    if match := TBANK_SAFE_PAYMENT_FALLBACK_RE.fullmatch(text):
        return _expense_candidate(
            bank=BankSmsBank.TBANK,
            amount_raw=match.group("amount"),
            merchant=_clean_party(match.group("merchant")),
            source=TransactionSource.TRANSFER,
            redacted_text=redacted_text,
        )

    return ParsedBankSms(
        bank=BankSmsBank.TBANK,
        operation_kind=BankSmsOperationKind.UNKNOWN,
        redacted_text=redacted_text,
        ignore_reason="unsupported_tbank_format",
    )


def _expense_candidate(
    *,
    bank: BankSmsBank,
    amount_raw: str,
    merchant: str,
    source: TransactionSource,
    redacted_text: str,
    fee_amount: int | None = None,
    is_adjusted_amount: bool = False,
    operation_time: time | None = None,
) -> ParsedBankSms:
    return ParsedBankSms(
        bank=bank,
        operation_kind=BankSmsOperationKind.EXPENSE_CANDIDATE,
        amount=_parse_amount(amount_raw),
        fee_amount=fee_amount,
        merchant=merchant,
        source=source,
        suggested_category_code=_suggest_category_code(merchant),
        requires_confirmation=True,
        redacted_text=redacted_text,
        is_adjusted_amount=is_adjusted_amount,
        operation_time=operation_time,
    )


def _detect_bank(text: str, sender: str) -> BankSmsBank:
    return detect_bank_from_profiles(text, sender)


def _ignored_redacted_text(bank: BankSmsBank, ignore_reason: str) -> str:
    return f"<{ignore_reason}:{bank.value}>"


def _ignore_reason(text: str) -> str:
    for pattern in IGNORE_PATTERNS:
        if pattern.search(text):
            return "ignored_non_transaction_message"
    return ""


def _suggest_category_code(merchant: str) -> str | None:
    merchant_normalized = merchant.upper()
    for aliases, category_code in CATEGORY_HINTS:
        if any(alias in merchant_normalized for alias in aliases):
            return category_code
    return None


def _vtb_payment_source(instrument: str) -> TransactionSource:
    if instrument.lower().startswith("карта"):
        return TransactionSource.CARD
    return TransactionSource.TRANSFER


def _sber_purchase_source(*, instrument: str, is_sbp: bool) -> TransactionSource:
    if is_sbp:
        return TransactionSource.TRANSFER
    if instrument.lower().startswith("счёт карты") or instrument.lower().startswith("счет карты"):
        return TransactionSource.CARD
    return TransactionSource.TRANSFER


def _is_self_counterparty(counterparty: str, self_aliases: set[str]) -> bool:
    if not counterparty or not self_aliases:
        return False
    return _normalize_counterparty(counterparty) in self_aliases


def _normalize_counterparty(value: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", value.lower())


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_party(value: str) -> str:
    return _normalize_text(value).strip(" ;,.")


def _parse_amount(value: str) -> int:
    return parse_amount_to_minor_units(value)


def _parse_operation_time(value: str | None) -> time | None:
    if value is None:
        return None
    hour_raw, minute_raw = value.split(":", maxsplit=1)
    try:
        return time(hour=int(hour_raw), minute=int(minute_raw))
    except ValueError:
        return None
