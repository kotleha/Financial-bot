from datetime import datetime
from zoneinfo import ZoneInfo

from financial_bot.app.bot.formatters.reports import format_period_report
from financial_bot.app.domain.periods import Period, PeriodKind
from financial_bot.app.services.report_service import (
    CategoryReportLine,
    PayerReportLine,
    PeriodReport,
)


def test_format_period_report_rounds_amounts_to_rubles() -> None:
    timezone = ZoneInfo("Asia/Barnaul")
    report = PeriodReport(
        period=Period(
            kind=PeriodKind.MONTH,
            start_at=datetime(2026, 5, 1, tzinfo=timezone),
            end_at=datetime(2026, 6, 1, tzinfo=timezone),
            label="Май 2026",
        ),
        total_amount=123456,
        currency="RUB",
        scope=None,
        by_payer=(
            PayerReportLine(role="husband", amount=123456, share_percent=100.0),
            PayerReportLine(role="wife", amount=0, share_percent=0.0),
        ),
        by_category=(
            CategoryReportLine(
                code="groceries",
                title="Продукты",
                owner_role="system",
                sort_order=2,
                amount=123456,
                share_percent=100.0,
            ),
        ),
    )

    formatted = format_period_report(report)

    assert "Фактические расходы: 1 235 ₽" in formatted
    assert "Муж — 1 235 ₽ — 100,0%" in formatted
    assert "Продукты — 1 235 ₽" in formatted


def test_format_empty_period_report() -> None:
    timezone = ZoneInfo("Asia/Barnaul")
    report = PeriodReport(
        period=Period(
            kind=PeriodKind.WEEK,
            start_at=datetime(2026, 6, 8, tzinfo=timezone),
            end_at=datetime(2026, 6, 15, tzinfo=timezone),
            label="Неделя 08.06.2026-14.06.2026",
        ),
        total_amount=0,
        currency="RUB",
        scope=None,
        by_payer=(
            PayerReportLine(role="husband", amount=0, share_percent=0.0),
            PayerReportLine(role="wife", amount=0, share_percent=0.0),
        ),
        by_category=(),
    )

    formatted = format_period_report(report)

    assert "Фактические расходы: 0 ₽" in formatted
    assert "За период расходов нет." in formatted
