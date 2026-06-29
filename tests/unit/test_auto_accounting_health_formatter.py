from datetime import datetime

from financial_bot.app.bot.formatters.auto_accounting_health import (
    format_auto_accounting_health,
)
from financial_bot.app.domain.types import BankCategoryRuleMode
from financial_bot.app.services.auto_accounting_health_service import (
    AutoAccountingHealth,
    AutoAccountingRuleHealth,
    AutoAccountingSourceHealth,
)


def test_auto_accounting_health_formatter_for_empty_sources() -> None:
    text = format_auto_accounting_health(
        AutoAccountingHealth(
            sources=(),
            active_source_count=0,
            inactive_source_count=0,
            pending_confirmation_count=0,
            failed_telegram_notification_count=0,
            unsent_pending_count=0,
            unknown_event_count=0,
            ignored_event_count=0,
        )
    )

    assert "Банковские источники ещё не заведены" in text


def test_auto_accounting_health_formatter_summarizes_sources_without_sensitive_payloads() -> None:
    text = format_auto_accounting_health(
        AutoAccountingHealth(
            sources=(
                AutoAccountingSourceHealth(
                    source_id=1,
                    code="husband-sber-ios",
                    bank="sber",
                    channel="ios_shortcut",
                    owner_role="husband",
                    owner_name="Husband",
                    is_active=True,
                    last_seen_at=datetime(2026, 6, 28, 9, 10),
                    last_event_received_at=datetime(2026, 6, 28, 9, 10),
                    pending_confirmation_count=2,
                    failed_telegram_notification_count=1,
                    unsent_pending_count=1,
                    unknown_event_count=3,
                    ignored_event_count=4,
                    total_event_count=12,
                    expense_candidate_count=6,
                    autosaved_expense_count=2,
                    confirmed_expense_count=1,
                    income_event_count=1,
                    refund_event_count=1,
                    internal_transfer_event_count=1,
                    conflict_event_count=2,
                ),
            ),
            active_source_count=1,
            inactive_source_count=0,
            pending_confirmation_count=2,
            failed_telegram_notification_count=1,
            unsent_pending_count=1,
            unknown_event_count=3,
            ignored_event_count=4,
            period_days=30,
            total_event_count=12,
            expense_candidate_count=6,
            autosaved_expense_count=2,
            confirmed_expense_count=1,
            income_event_count=1,
            refund_event_count=1,
            internal_transfer_event_count=1,
            conflict_event_count=2,
            autosave_rule_count=1,
            suggest_rule_count=2,
            disabled_rule_count=3,
            top_rules=(
                AutoAccountingRuleHealth(
                    id=1,
                    bank="sber",
                    merchant_display="MAGNIT",
                    category_title="Продукты",
                    hit_count=4,
                    mode=BankCategoryRuleMode.AUTOSAVE,
                    last_confirmed_at=datetime(2026, 6, 28, 9, 10),
                    last_used_at=datetime(2026, 6, 28, 9, 10),
                ),
            ),
        )
    )

    assert "SBER · муж · iPhone" in text
    assert "Состояние автоучёта за 30 дней" in text
    assert "Поток SMS" in text
    assert "Всего событий: 12" in text
    assert "Сохранено в расходы: 3 (авто 2, вручную 1)" in text
    assert "Ждут подтверждения: 2" in text
    assert "Не расходы: доходы 1, возвраты 1, переводы себе 1" in text
    assert "Ошибки доставки в Telegram: 1" in text
    assert "Неизвестный формат: 3" in text
    assert "Служебные/реклама: 4" in text
    assert "Спорные подсказки категорий: 2" in text
    assert "Правила категорий:" in text
    assert "авто 1, подсказки 2, выключены 3" in text
    assert "SBER · MAGNIT → Продукты" in text
    assert "Последнее SMS: 28.06.2026 09:10" in text
    assert "token" not in text.lower()
    assert "authorization" not in text.lower()
    assert "Счёт карты" not in text
    assert "Баланс" not in text
