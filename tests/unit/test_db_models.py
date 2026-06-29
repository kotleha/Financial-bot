from financial_bot.app.domain.types import (
    BankEventBank,
    BankEventChannel,
    BankEventOperationKind,
    BankEventParseStatus,
    BankEventSuggestionSource,
    CategoryOwnerRole,
    TransactionSource,
    TransactionType,
    UserRole,
)
from financial_bot.app.storage.models import BankEventModel, Base, TransactionModel
from sqlalchemy import CheckConstraint, UniqueConstraint


def test_metadata_contains_required_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "categories",
        "category_aliases",
        "transactions",
        "settings",
        "operation_audit_log",
        "spending_limit_alerts",
        "bank_event_sources",
        "bank_events",
        "bank_category_rules",
    }


def test_user_table_constraints() -> None:
    users = Base.metadata.tables["users"]

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in users.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("telegram_id",) in unique_columns
    assert ("role",) in unique_columns


def test_transaction_table_has_financial_and_soft_delete_columns() -> None:
    transactions = Base.metadata.tables["transactions"]

    assert transactions.c.amount.type.python_type is int
    assert transactions.c.currency.type.length == 3
    assert "included_in_reports" in transactions.c
    assert "deleted_at" in transactions.c


def test_transaction_table_has_expected_check_constraints() -> None:
    transactions = Base.metadata.tables["transactions"]
    check_constraint_names = {
        constraint.name
        for constraint in transactions.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_transactions_transactions_amount_positive" in check_constraint_names
    assert "ck_transactions_transactions_type" in check_constraint_names
    assert "ck_transactions_transactions_source" in check_constraint_names


def test_domain_enum_values_match_database_contract() -> None:
    assert {item.value for item in UserRole} == {"husband", "wife"}
    assert {item.value for item in CategoryOwnerRole} == {"husband", "wife", "system"}
    assert {item.value for item in TransactionType} == {
        "expense",
        "income",
        "internal_transfer",
        "correction",
    }
    assert {item.value for item in TransactionSource} == {
        "card",
        "cash",
        "transfer",
        "unknown",
    }
    assert {item.value for item in BankEventBank} == {"vtb", "sber", "tbank", "unknown"}
    assert {item.value for item in BankEventChannel} == {
        "ios_shortcut",
        "manual_telegram",
        "email",
        "android_notification",
    }
    assert {item.value for item in BankEventOperationKind} == {
        "expense_candidate",
        "income",
        "internal_transfer",
        "refund",
        "ignored",
        "unknown",
    }
    assert {item.value for item in BankEventParseStatus} == {
        "ignored",
        "parsed",
        "needs_confirmation",
        "confirmed",
        "rejected",
        "autosaved",
    }
    assert {item.value for item in BankEventSuggestionSource} == {
        "parser_hint",
        "learned_rule",
        "manual",
        "none",
    }


def test_transaction_model_uses_integer_amounts() -> None:
    transaction = TransactionModel(amount=350000, currency="RUB")

    assert transaction.amount == 350000


def test_bank_event_tables_have_expected_constraints() -> None:
    bank_event_sources = Base.metadata.tables["bank_event_sources"]
    bank_events = Base.metadata.tables["bank_events"]
    bank_category_rules = Base.metadata.tables["bank_category_rules"]

    source_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in bank_event_sources.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    event_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in bank_events.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    event_check_constraint_names = {
        constraint.name
        for constraint in bank_events.constraints
        if isinstance(constraint, CheckConstraint)
    }
    rule_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in bank_category_rules.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("code",) in source_unique_columns
    assert ("token_hash",) in source_unique_columns
    assert ("dedupe_key",) in event_unique_columns
    assert ("owner_user_id", "bank", "merchant_key") in rule_unique_columns
    assert "ck_bank_events_bank_events_operation_kind" in event_check_constraint_names
    assert "ck_bank_events_bank_events_parse_status" in event_check_constraint_names
    assert "ck_bank_events_bank_events_source" in event_check_constraint_names
    assert "ck_bank_events_bank_events_suggested_category_source" in event_check_constraint_names


def test_bank_event_model_uses_integer_amounts() -> None:
    event = BankEventModel(amount=29000, currency="RUB")

    assert event.amount == 29000
