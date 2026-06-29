from datetime import UTC, datetime

from financial_bot.app.bot.formatters.bank_events import (
    format_bank_event_autosaved,
    format_bank_event_confirmed,
    format_bank_event_income_confirmed,
    format_bank_event_refund_corrected,
    format_bank_event_rule_disabled,
    format_bank_import_result,
)
from financial_bot.app.domain.types import (
    BankCategoryRuleMode,
    BankEventBank,
    BankEventOperationKind,
    BankEventParseStatus,
    BankEventSuggestionSource,
)
from financial_bot.app.services.bank_ingestion_service import (
    BankEventConfirmationResult,
    BankEventUpdateResult,
    BankImportResult,
)
from financial_bot.app.services.bank_learning_service import BankLearningRuleFeedback
from financial_bot.app.services.transaction_service import CreatedTransactionSummary


def test_format_bank_import_result_for_expense_candidate() -> None:
    text = format_bank_import_result(
        BankImportResult(
            event_id=42,
            is_duplicate=False,
            bank=BankEventBank.SBER,
            operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE,
            parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
            amount=29_000,
            fee_amount=None,
            currency="RUB",
            merchant="APTEKA TEST",
            counterparty="",
            suggested_category_code="cosmetology_medicine",
            suggested_category_title="Косметология/Медицина",
            suggested_category_source=BankEventSuggestionSource.PARSER_HINT,
            requires_confirmation=True,
            ignore_reason="",
            redacted_text="redacted",
        )
    )

    assert "Разобрал банковское SMS:" in text
    assert "Событие: #42" in text
    assert "Сумма: 290 ₽" in text
    assert "Категория-кандидат: Косметология/Медицина (по SMS-подсказке)" in text
    assert "Почему так: SMS или продавец похожи на известные слова этой категории." in text
    assert "Пока не записываю в расходы" in text


def test_format_bank_import_result_explains_learned_rule() -> None:
    text = format_bank_import_result(
        BankImportResult(
            event_id=42,
            is_duplicate=False,
            bank=BankEventBank.SBER,
            operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE,
            parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
            amount=29_000,
            fee_amount=None,
            currency="RUB",
            merchant="UNKNOWN SHOP",
            counterparty="",
            suggested_category_code="groceries",
            suggested_category_title="Продукты",
            suggested_category_source=BankEventSuggestionSource.LEARNED_RULE,
            requires_confirmation=True,
            ignore_reason="",
            redacted_text="redacted",
        )
    )

    assert "Категория-кандидат: Продукты (по прошлым подтверждениям)" in text
    assert "Почему так: похожего продавца уже подтверждали в этой категории." in text


def test_format_bank_import_result_explains_learning_conflict() -> None:
    text = format_bank_import_result(
        BankImportResult(
            event_id=42,
            is_duplicate=False,
            bank=BankEventBank.SBER,
            operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE,
            parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
            amount=29_000,
            fee_amount=None,
            currency="RUB",
            merchant="APTEKA TEST",
            counterparty="",
            suggested_category_code="groceries",
            suggested_category_title="Продукты",
            suggested_category_source=BankEventSuggestionSource.LEARNED_RULE,
            requires_confirmation=True,
            ignore_reason="",
            redacted_text="redacted",
            suggestion_conflict=True,
        )
    )

    assert "Автосохранение остановлено" in text
    assert "дали разные категории" in text


def test_format_bank_import_result_for_internal_transfer() -> None:
    text = format_bank_import_result(
        BankImportResult(
            event_id=43,
            is_duplicate=True,
            bank=BankEventBank.VTB,
            operation_kind=BankEventOperationKind.INTERNAL_TRANSFER,
            parse_status=BankEventParseStatus.PARSED,
            amount=10_000,
            fee_amount=None,
            currency="RUB",
            merchant="",
            counterparty="self",
            suggested_category_code="internal_transfer",
            suggested_category_title="Самоперевод / внутренний перевод",
            suggested_category_source=BankEventSuggestionSource.PARSER_HINT,
            requires_confirmation=False,
            ignore_reason="",
            redacted_text="redacted",
        )
    )

    assert "Уже видел это SMS:" in text
    assert "внутренний перевод, не расход" in text
    assert "Контрагент: свой счёт" in text
    assert "Перевод между своими счетами: в расходы, лимиты и графики категорий не попадёт." in text


def test_format_bank_import_result_for_income_explains_explicit_confirm_flow() -> None:
    text = format_bank_import_result(
        BankImportResult(
            event_id=45,
            is_duplicate=False,
            bank=BankEventBank.SBER,
            operation_kind=BankEventOperationKind.INCOME,
            parse_status=BankEventParseStatus.PARSED,
            amount=50_000_00,
            fee_amount=None,
            currency="RUB",
            merchant="",
            counterparty="",
            suggested_category_code=None,
            suggested_category_title=None,
            suggested_category_source=BankEventSuggestionSource.NONE,
            requires_confirmation=False,
            ignore_reason="",
            redacted_text="redacted",
        )
    )

    assert "Тип: поступление" in text
    assert "Сумма: 50 000 ₽" in text
    assert "Это поступление. Пока не записываю его в доходы." in text
    assert "Если это семейный доход, нажмите «Учесть доход»." in text
    assert "В расходные лимиты и графики категорий он не попадёт." in text
    assert "Пока не записываю в расходы" not in text


def test_format_bank_import_result_for_refund_explains_it_is_not_income() -> None:
    text = format_bank_import_result(
        BankImportResult(
            event_id=46,
            is_duplicate=False,
            bank=BankEventBank.SBER,
            operation_kind=BankEventOperationKind.REFUND,
            parse_status=BankEventParseStatus.PARSED,
            amount=1_794_00,
            fee_amount=None,
            currency="RUB",
            merchant="Gloria Jeans",
            counterparty="",
            suggested_category_code="clothing_shoes",
            suggested_category_title="Одежда/Обувь",
            suggested_category_source=BankEventSuggestionSource.PARSER_HINT,
            requires_confirmation=False,
            ignore_reason="",
            redacted_text="redacted",
        )
    )

    assert "Тип: возврат" in text
    assert "Это возврат, не новый доход и не расход." in text
    assert "Без подтверждения расходы не меняю" in text
    assert "Можно учесть возврат как корректировку" in text
    assert "Пока не записываю в расходы" not in text


def test_format_bank_event_confirmed() -> None:
    text = format_bank_event_confirmed(
        BankEventConfirmationResult(
            event_id=44,
            transaction=CreatedTransactionSummary(
                id=100,
                amount=29_000,
                currency="RUB",
                category_code="cosmetology_medicine",
                category_title="Косметология/Медицина",
                payer_role="husband",
                occurred_at=datetime(2026, 6, 26, tzinfo=UTC),
                included_in_reports=True,
            ),
        )
    )

    assert "✅ Записал расход:" in text
    assert "290 ₽ — Косметология/Медицина" in text
    assert "Статус: подтверждено" in text
    assert "Событие: #44" not in text
    assert "Запомнил" not in text


def test_format_bank_event_confirmed_with_created_learning_rule() -> None:
    text = format_bank_event_confirmed(
        BankEventConfirmationResult(
            event_id=44,
            transaction=_created_transaction_summary(),
            learning_rule=BankLearningRuleFeedback(
                rule_id=7,
                action="created",
                merchant_display="UNKNOWN SHOP",
                category_title="Продукты",
                hit_count=1,
                mode=BankCategoryRuleMode.SUGGEST,
            ),
        )
    )

    assert "Запомнил для будущих SMS: UNKNOWN SHOP → Продукты." in text
    assert "Если подтвердите похожее SMS ещё раз" in text
    assert "Режим правила можно изменить в «🧠 Правила категорий»" in text
    assert "MIR-1111" not in text
    assert "Баланс" not in text
    assert "secret" not in text


def test_format_bank_event_confirmed_with_reinforced_learning_rule() -> None:
    text = format_bank_event_confirmed(
        BankEventConfirmationResult(
            event_id=44,
            transaction=_created_transaction_summary(),
            learning_rule=BankLearningRuleFeedback(
                rule_id=7,
                action="reinforced",
                merchant_display="UNKNOWN SHOP",
                category_title="Продукты",
                hit_count=2,
                mode=BankCategoryRuleMode.AUTOSAVE,
            ),
        )
    )

    assert "Укрепил правило: UNKNOWN SHOP → Продукты. Подтверждений: 2." in text
    assert "Следующие похожие SMS будут записываться автоматически." in text


def test_format_bank_event_confirmed_with_updated_learning_rule() -> None:
    text = format_bank_event_confirmed(
        BankEventConfirmationResult(
            event_id=44,
            transaction=_created_transaction_summary(category_title="Дом/Участок"),
            learning_rule=BankLearningRuleFeedback(
                rule_id=7,
                action="updated",
                merchant_display="UNKNOWN SHOP",
                category_title="Дом/Участок",
                hit_count=1,
                mode=BankCategoryRuleMode.SUGGEST,
            ),
        )
    )

    assert "Обновил правило для будущих SMS: UNKNOWN SHOP → Дом/Участок." in text
    assert "Если подтвердите похожее SMS ещё раз" in text


def test_format_bank_event_confirmed_with_disabled_learning_rule() -> None:
    text = format_bank_event_confirmed(
        BankEventConfirmationResult(
            event_id=44,
            transaction=_created_transaction_summary(category_title="Продукты"),
            learning_rule=BankLearningRuleFeedback(
                rule_id=7,
                action="reinforced",
                merchant_display="UNKNOWN SHOP",
                category_title="Продукты",
                hit_count=4,
                mode=BankCategoryRuleMode.DISABLED,
            ),
        )
    )

    assert "Отключённое правило не включал" in text
    assert "не будет применять это правило" in text
    assert "будут записываться автоматически" not in text


def test_format_bank_event_refund_corrected() -> None:
    text = format_bank_event_refund_corrected(
        BankEventConfirmationResult(
            event_id=46,
            transaction=CreatedTransactionSummary(
                id=101,
                amount=1_794_00,
                currency="RUB",
                category_code="clothing_shoes",
                category_title="Одежда/Обувь",
                payer_role="husband",
                occurred_at=datetime(2026, 6, 26, tzinfo=UTC),
                included_in_reports=True,
            ),
        )
    )

    assert "↩️ Учёл возврат:" in text
    assert "-1 794 ₽ — Одежда/Обувь" in text
    assert "Событие: #46" not in text


def test_format_bank_event_income_confirmed() -> None:
    text = format_bank_event_income_confirmed(
        BankEventConfirmationResult(
            event_id=45,
            transaction=CreatedTransactionSummary(
                id=102,
                amount=50_000_00,
                currency="RUB",
                category_code="income_general",
                category_title="Доходы",
                payer_role="husband",
                occurred_at=datetime(2026, 6, 26, tzinfo=UTC),
                included_in_reports=False,
            ),
        )
    )

    assert "✅ Учёл доход:" in text
    assert "+50 000 ₽ — Доходы" in text
    assert "Событие: #45" not in text
    assert "Доходы не входят в расходные лимиты, графики категорий и отчёты по расходам." in text
    assert "MIR-1111" not in text
    assert "Баланс" not in text


def test_format_bank_event_autosaved_is_compact_and_without_buttons_context() -> None:
    text = format_bank_event_autosaved(
        BankImportResult(
            event_id=47,
            is_duplicate=False,
            bank=BankEventBank.SBER,
            operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE,
            parse_status=BankEventParseStatus.AUTOSAVED,
            amount=15_000,
            fee_amount=None,
            currency="RUB",
            merchant="UNKNOWN SHOP",
            counterparty="",
            suggested_category_code="groceries",
            suggested_category_title="Продукты",
            suggested_category_source=BankEventSuggestionSource.LEARNED_RULE,
            requires_confirmation=False,
            ignore_reason="",
            redacted_text="redacted",
        )
    )

    assert "✅ Записал автоматически:" in text
    assert "150 ₽ — Продукты" in text
    assert "Основание: похожего продавца уже подтверждали в этой категории." in text
    assert "Кнопки ниже меняют уже записанную операцию" in text
    assert "Событие" not in text
    assert "MIR-1111" not in text


def test_format_bank_event_rule_disabled_keeps_existing_expense() -> None:
    text = format_bank_event_rule_disabled(
        BankEventUpdateResult(
            event_id=47,
            operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE,
            parse_status=BankEventParseStatus.AUTOSAVED,
            amount=15_000,
            currency="RUB",
            merchant="UNKNOWN SHOP",
            counterparty="",
            suggested_category_code="groceries",
            suggested_category_title="Продукты",
            suggested_category_source=BankEventSuggestionSource.LEARNED_RULE,
        )
    )

    assert "🚫 Правило автоучёта отключено:" in text
    assert "150 ₽ — Продукты" in text
    assert "Записанный расход не изменил." in text


def _created_transaction_summary(category_title: str = "Продукты") -> CreatedTransactionSummary:
    return CreatedTransactionSummary(
        id=100,
        amount=29_000,
        currency="RUB",
        category_code="groceries",
        category_title=category_title,
        payer_role="husband",
        occurred_at=datetime(2026, 6, 26, tzinfo=UTC),
        included_in_reports=True,
    )
