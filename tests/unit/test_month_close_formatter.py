from types import SimpleNamespace

from financial_bot.app.bot.formatters.month_close import format_month_close_report
from financial_bot.app.domain.monthly_insights import ScopeSnapshot
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.month_close_service import (
    MonthCloseChecklistItem,
    MonthCloseItemStatus,
    MonthCloseReport,
)


def test_month_close_formatter_groups_readiness_checklist_and_financial_orientation() -> None:
    report = MonthCloseReport(
        summary=SimpleNamespace(
            report=SimpleNamespace(
                period=SimpleNamespace(label="Июль 2026"),
                currency="RUB",
                income_total=120_000_00,
                total_amount=70_000_00,
                net_after_expenses=50_000_00,
                net_savings=30_000_00,
                has_expenses=True,
            ),
            scope_snapshots=(
                ScopeSnapshot(
                    scope=TransactionScope.HOUSEHOLD,
                    expenses=40_000_00,
                    income=100_000_00,
                    net_after_expenses=60_000_00,
                ),
                ScopeSnapshot(
                    scope=TransactionScope.SALON,
                    expenses=30_000_00,
                    income=20_000_00,
                    net_after_expenses=-10_000_00,
                ),
            ),
        ),
        auto_accounting_health=None,
        checklist=(
            MonthCloseChecklistItem(
                code="bank_auto_accounting",
                status=MonthCloseItemStatus.BLOCKED,
                title="Автоучёт",
                message="Сначала разберите банковские события: 1 ожидает подтверждения.",
                sort_order=10,
            ),
            MonthCloseChecklistItem(
                code="income",
                status=MonthCloseItemStatus.OK,
                title="Доходы",
                message="Внесено доходов: 120 000 ₽.",
                sort_order=20,
            ),
            MonthCloseChecklistItem(
                code="cashflow",
                status=MonthCloseItemStatus.ATTENTION,
                title="Денежный поток",
                message="Проверьте контур Салон.",
                sort_order=30,
            ),
        ),
        blocked_count=1,
        attention_count=1,
    )

    text = format_month_close_report(report)

    assert "Закрытие месяца: Июль 2026" in text
    assert "Готовность" in text
    assert "Чеклист" in text
    assert "⛔ Автоучёт" in text
    assert "✅ Доходы" in text
    assert "⚠️ Денежный поток" in text
    assert "Доходы: 120 000 ₽" in text
    assert "Расходы: 70 000 ₽" in text
    assert "После расходов: +50 000 ₽" in text
    assert "Резерв по лимитам: +30 000 ₽" in text
    assert "Дом: расходы 40 000 ₽, доходы 100 000 ₽, итог +60 000 ₽" in text
    assert "Салон: расходы 30 000 ₽, доходы 20 000 ₽, итог -10 000 ₽" in text
    assert "SHABBA" not in text
    assert "raw bank payload" not in text
    assert "Bearer" not in text
