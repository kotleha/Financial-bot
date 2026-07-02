from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from financial_bot.app.bot.formatters.month_reports import (
    format_month_report,
    format_smart_month_summary,
)
from financial_bot.app.domain.monthly_insights import (
    AutoAccountingQuality,
    ScopeSnapshot,
    build_month_conclusion,
)
from financial_bot.app.domain.periods import Period, PeriodKind
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.cashflow_service import IncomeCategoryLine, IncomeRecipientLine
from financial_bot.app.services.month_report_service import MonthPace, MonthReport
from financial_bot.app.services.report_service import CategoryReportLine, PayerReportLine
from financial_bot.app.services.smart_month_summary_service import SmartMonthSummary
from financial_bot.app.services.spending_limit_service import (
    BudgetLimitLine,
    BudgetReport,
    BudgetSavingsTargetLine,
)


def test_format_month_report_groups_data_without_full_dump() -> None:
    report = _sample_month_report()

    formatted = format_month_report(report)

    assert "Итог месяца: Май 2026" in formatted
    assert "Главное\nДень месяца: 20 из 31" in formatted
    assert "Доходы: 600 000 ₽" in formatted
    assert "Расходы: 523 244 ₽" in formatted
    assert "После расходов: +76 756 ₽" in formatted
    assert "Темп расходов: 26 162 ₽/день" in formatted
    assert "Прогноз расходов: 811 028 ₽" in formatted
    assert "Вывод" in formatted
    assert "Месяц сейчас в плюсе после расходов." in formatted
    assert "Что важно" in formatted
    assert "ЖКХ превысил лимит на 114 184 ₽." in formatted
    assert "Месяц: после расходов плюс 76 756 ₽." in formatted
    assert "Расходы по категориям" in formatted
    assert "1. ЖКХ — 122 184 ₽ (23,4%)" in formatted
    assert "Остальные 4 категории — 72 000 ₽" in formatted
    assert "Доходы по источникам" in formatted
    assert "1. Зарплата — 550 000 ₽ (91,7%)" in formatted
    assert "Лимиты и резерв" in formatted
    assert "Нужно компенсировать перерасход: 20 000 ₽" in formatted
    assert "Инвестиции/Накопления: внесено 0 ₽ из 30 000 ₽" in formatted
    assert "Под вниманием" not in formatted
    assert "Кто платил" in formatted
    assert "Муж — 363 170 ₽ (69,4%)" in formatted
    assert "Кому пришли доходы" in formatted
    assert "Жена — 550 000 ₽ (91,7%)" in formatted
    assert "Доходы и реальный остаток будут в отдельном слайсе." not in formatted
    assert "Скрытая категория" not in formatted


def test_format_empty_month_report_hides_financial_summary() -> None:
    report = _sample_month_report(
        total_amount=0,
        income_total=0,
        top_categories=(),
        other_amount=0,
    )

    formatted = format_month_report(report)

    assert "За месяц пока нет данных для финансового вывода." in formatted
    assert "бот соберёт полный итог месяца" in formatted
    assert "Можно отложить" not in formatted
    assert "999 999 ₽" not in formatted


def test_format_empty_smart_month_summary_keeps_auto_accounting_warnings() -> None:
    report = _sample_month_report(
        total_amount=0,
        income_total=0,
        top_categories=(),
        other_amount=0,
    )
    quality = AutoAccountingQuality(
        pending_confirmation_count=2,
        failed_telegram_notification_count=1,
    )
    summary = SmartMonthSummary(
        report=report,
        conclusion=build_month_conclusion(report, auto_accounting_quality=quality),
        scope_snapshots=(),
        auto_accounting_quality=quality,
    )

    formatted = format_smart_month_summary(summary)

    assert "Есть банковские события, которые не удалось отправить в Telegram: 1." in formatted
    assert "Ждут подтверждения банковские операции: 2." in formatted
    assert "бот соберёт полный итог месяца" in formatted


def test_format_income_only_month_report_does_not_show_expense_forecast() -> None:
    report = _sample_month_report(
        total_amount=0,
        income_total=120_000_00,
        top_categories=(),
        other_amount=0,
    )

    formatted = format_month_report(report)

    assert "Доходы: 120 000 ₽" in formatted
    assert "Расходы: 0 ₽" in formatted
    assert "После расходов: +120 000 ₽" in formatted
    assert "Темп расходов" not in formatted
    assert "Прогноз расходов" not in formatted
    assert "Расходы по категориям" not in formatted
    assert "Доходы по источникам" in formatted
    assert "Месяц: доходы внесены, расходов пока нет." in formatted
    assert "Можно отложить" not in formatted
    assert "999 999 ₽" not in formatted


def test_format_negative_cashflow_does_not_say_money_can_be_saved() -> None:
    report = replace(
        _sample_month_report(income_total=20_000_00),
        under_budget_pool=12_000_00,
        overrun_total=2_000_00,
        net_savings=10_000_00,
    )

    formatted = format_month_report(report)

    assert "Свободный резерв есть по лимитам, но реальный cashflow сейчас в минусе." in formatted
    assert "Можно отложить по лимитам" not in formatted


def test_format_scoped_month_report_hides_budget_math() -> None:
    report = _sample_month_report(scope=TransactionScope.SALON)

    formatted = format_month_report(report)

    assert "Контур: Салон" in formatted
    assert "Лимиты и копилка считаются только в общем отчёте по всем контурам." in formatted
    assert "Лимиты и резерв" not in formatted
    assert "Нужно компенсировать перерасход" not in formatted
    assert "Под вниманием" not in formatted
    assert "Инвестиции/Накопления" not in formatted


def test_format_smart_month_summary_includes_scope_snapshots() -> None:
    report = _sample_month_report()
    snapshots = (
        ScopeSnapshot(
            scope=TransactionScope.HOUSEHOLD,
            expenses=40_000_00,
            income=120_000_00,
            net_after_expenses=80_000_00,
            top_category_title="Продукты",
        ),
        ScopeSnapshot(
            scope=TransactionScope.SALON,
            expenses=90_000_00,
            income=70_000_00,
            net_after_expenses=-20_000_00,
            top_category_title="Канцелярия/Расходники",
        ),
    )
    summary = SmartMonthSummary(
        report=report,
        conclusion=build_month_conclusion(report, scope_snapshots=snapshots, max_insights=8),
        scope_snapshots=snapshots,
    )

    formatted = format_smart_month_summary(summary)

    assert "Дом и Салон" in formatted
    assert "Дом: расходы 40 000 ₽, доходы 120 000 ₽, итог +80 000 ₽" in formatted
    assert "Салон: расходы 90 000 ₽, доходы 70 000 ₽, итог -20 000 ₽" in formatted
    assert "Салон пока в минусе на 20 000 ₽." in formatted


def _sample_month_report(
    *,
    total_amount: int = 52_324_400,
    income_total: int = 60_000_000,
    top_categories: tuple[CategoryReportLine, ...] | None = None,
    other_amount: int = 7_200_000,
    scope: TransactionScope | None = None,
) -> MonthReport:
    timezone = ZoneInfo("Asia/Barnaul")
    period = Period(
        kind=PeriodKind.MONTH,
        start_at=datetime(2026, 5, 1, tzinfo=timezone),
        end_at=datetime(2026, 6, 1, tzinfo=timezone),
        label="Май 2026",
    )
    budget = BudgetReport(
        period=period,
        currency="RUB",
        limit_lines=(),
        no_limit_lines=(),
        savings_target_lines=(
            BudgetSavingsTargetLine(
                code="investments_savings",
                title="Инвестиции/Накопления",
                sort_order=15,
                actual_amount=0,
                target_amount=3_000_000,
                delta_amount=-3_000_000,
                usage_percent=0.0,
            ),
        ),
        under_budget_pool=10_000_000,
        overrun_total=12_000_000,
        net_savings=-2_000_000,
    )
    bonus_income = min(income_total, 5_000_000)
    salary_income = max(income_total - bonus_income, 0)
    return MonthReport(
        period=period,
        currency="RUB",
        scope=scope,
        total_amount=total_amount,
        income_total=income_total,
        net_after_expenses=income_total - total_amount,
        pace=MonthPace(
            elapsed_days=20,
            day_count=31,
            average_per_day=2_616_200,
            forecast_amount=81_102_800,
        ),
        by_payer=(
            PayerReportLine(role="husband", amount=36_317_000, share_percent=69.4),
            PayerReportLine(role="wife", amount=16_007_400, share_percent=30.6),
        ),
        top_categories=top_categories
        if top_categories is not None
        else (
            CategoryReportLine(
                code="utilities",
                title="ЖКХ",
                owner_role="system",
                sort_order=1,
                amount=12_218_400,
                share_percent=23.4,
            ),
        ),
        other_categories_count=4 if other_amount else 0,
        other_categories_amount=other_amount,
        income_by_recipient=(
            IncomeRecipientLine(
                role="husband",
                amount=bonus_income,
                share_percent=_share(bonus_income, income_total),
            ),
            IncomeRecipientLine(
                role="wife",
                amount=salary_income,
                share_percent=_share(salary_income, income_total),
            ),
        )
        if income_total
        else (),
        top_income_categories=(
            IncomeCategoryLine(
                code="income_salary",
                title="Зарплата",
                amount=salary_income,
                share_percent=_share(salary_income, income_total),
            ),
            IncomeCategoryLine(
                code="income_bonus",
                title="Премия/Бонус",
                amount=bonus_income,
                share_percent=_share(bonus_income, income_total),
            ),
        )
        if income_total
        else (),
        other_income_categories_count=0,
        other_income_categories_amount=0,
        budget_risks=(
            BudgetLimitLine(
                code="utilities",
                title="ЖКХ",
                sort_order=1,
                spent_amount=12_218_400,
                limit_amount=800_000,
                usage_percent=1527.3,
                remaining_amount=-11_418_400,
            ),
        ),
        no_limit_lines=(),
        savings_target_lines=budget.savings_target_lines,
        under_budget_pool=budget.under_budget_pool if total_amount else 99_999_900,
        overrun_total=budget.overrun_total,
        net_savings=budget.net_savings if total_amount else 99_999_900,
        budget=budget,
    )


def _share(amount: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(amount / total * 100, 1)
