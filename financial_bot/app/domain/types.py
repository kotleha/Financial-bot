from enum import StrEnum


class UserRole(StrEnum):
    HUSBAND = "husband"
    WIFE = "wife"


class CategoryOwnerRole(StrEnum):
    HUSBAND = "husband"
    WIFE = "wife"
    SYSTEM = "system"


class TransactionType(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    INTERNAL_TRANSFER = "internal_transfer"
    CORRECTION = "correction"


class TransactionSource(StrEnum):
    CARD = "card"
    CASH = "cash"
    TRANSFER = "transfer"
    UNKNOWN = "unknown"


class BankEventBank(StrEnum):
    VTB = "vtb"
    SBER = "sber"
    TBANK = "tbank"
    UNKNOWN = "unknown"


class BankEventChannel(StrEnum):
    IOS_SHORTCUT = "ios_shortcut"
    MANUAL_TELEGRAM = "manual_telegram"
    EMAIL = "email"
    ANDROID_NOTIFICATION = "android_notification"


class BankEventOperationKind(StrEnum):
    EXPENSE_CANDIDATE = "expense_candidate"
    INCOME = "income"
    INTERNAL_TRANSFER = "internal_transfer"
    REFUND = "refund"
    IGNORED = "ignored"
    UNKNOWN = "unknown"


class BankEventParseStatus(StrEnum):
    IGNORED = "ignored"
    PARSED = "parsed"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    AUTOSAVED = "autosaved"


class BankEventSuggestionSource(StrEnum):
    PARSER_HINT = "parser_hint"
    LEARNED_RULE = "learned_rule"
    MANUAL = "manual"
    NONE = "none"


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
