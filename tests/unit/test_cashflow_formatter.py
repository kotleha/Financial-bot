from datetime import datetime
from zoneinfo import ZoneInfo

from financial_bot.app.bot.formatters.cashflow import format_cashflow_report
from financial_bot.app.domain.periods import Period, PeriodKind
from financial_bot.app.services.cashflow_service import (
    CashflowReport,
    IncomeCategoryLine,
    IncomeRecipientLine,
)


def test_format_cashflow_report_groups_income_before_recipients() -> None:
    timezone = ZoneInfo("Asia/Barnaul")
    report = CashflowReport(
        period=Period(
            kind=PeriodKind.MONTH,
            label="Июнь 2026",
            start_at=datetime(2026, 6, 1, tzinfo=timezone),
            end_at=datetime(2026, 7, 1, tzinfo=timezone),
        ),
        currency="RUB",
        income_total=125_000_00,
        expense_total=25_000_00,
        net_after_expenses=100_000_00,
        income_by_recipient=(
            IncomeRecipientLine(role="husband", amount=100_000_00, share_percent=80.0),
            IncomeRecipientLine(role="wife", amount=25_000_00, share_percent=20.0),
        ),
        income_by_category=(
            IncomeCategoryLine(
                code="income_salary",
                title="Зарплата",
                amount=100_000_00,
                share_percent=80.0,
            ),
            IncomeCategoryLine(
                code="income_bonus",
                title="Премия/Бонус",
                amount=25_000_00,
                share_percent=20.0,
            ),
        ),
        budget_net_savings=30_000_00,
    )

    text = format_cashflow_report(report)

    assert "Доходы по источникам:" in text
    assert "Зарплата — 100 000 ₽ — 80,0%" in text
    assert "Премия/Бонус — 25 000 ₽ — 20,0%" in text
    assert "Доходы по получателю:" in text
    assert "Муж — 100 000 ₽ — 80,0%" in text
    assert "Жена — 25 000 ₽ — 20,0%" in text
