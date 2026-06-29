from datetime import datetime

from financial_bot.app.bot.formatters.auto_accounting_health import (
    format_auto_accounting_health,
)
from financial_bot.app.services.auto_accounting_health_service import (
    AutoAccountingHealth,
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
                ),
            ),
            active_source_count=1,
            inactive_source_count=0,
            pending_confirmation_count=2,
            failed_telegram_notification_count=1,
            unsent_pending_count=1,
            unknown_event_count=3,
            ignored_event_count=4,
        )
    )

    assert "SBER · муж · iPhone" in text
    assert "Ожидают подтверждения: 2" in text
    assert "Ошибки отправки в Telegram: 1" in text
    assert "Не распознаны: 3" in text
    assert "Игнорированы как служебные: 4" in text
    assert "Последнее SMS: 28.06.2026 09:10" in text
    assert "token" not in text.lower()
    assert "authorization" not in text.lower()
    assert "Счёт карты" not in text
    assert "Баланс" not in text
