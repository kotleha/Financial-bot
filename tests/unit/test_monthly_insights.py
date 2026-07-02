from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from financial_bot.app.domain.monthly_insights import (
    AutoAccountingQuality,
    CategoryChange,
    MonthInsightSeverity,
    ScopeSnapshot,
    build_month_conclusion,
)
from financial_bot.app.domain.periods import Period, PeriodKind
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.cashflow_service import IncomeCategoryLine, IncomeRecipientLine
from financial_bot.app.services.month_report_service import MonthPace, MonthReport
from financial_bot.app.services.report_service import CategoryReportLine, PayerReportLine
from financial_bot.app.services.spending_limit_service import (
    BudgetLimitLine,
    BudgetNoLimitLine,
    BudgetReport,
    BudgetSavingsTargetLine,
)


def test_empty_month_gets_neutral_conclusion() -> None:
    conclusion = build_month_conclusion(_report(total_amount=0, income_total=0))

    assert conclusion.headline == "За месяц пока нет данных для финансового вывода."
    assert conclusion.details is None
    assert [(item.severity, item.code) for item in conclusion.insights] == [
        (MonthInsightSeverity.INFO, "empty_month")
    ]


def test_positive_cashflow_and_savings_are_positive_insights() -> None:
    conclusion = build_month_conclusion(
        _report(
            total_amount=120_000_00,
            income_total=200_000_00,
            under_budget_pool=40_000_00,
            overrun_total=5_000_00,
            net_savings=35_000_00,
        )
    )

    assert conclusion.headline == "Месяц сейчас в плюсе после расходов."
    assert "можно отложить до 35 000 ₽" in (conclusion.details or "")
    assert "positive_cashflow" in _codes(conclusion)
    assert "savings_available" in _codes(conclusion)


def test_negative_cashflow_does_not_present_savings_as_real_balance() -> None:
    conclusion = build_month_conclusion(
        _report(
            total_amount=230_000_00,
            income_total=200_000_00,
            under_budget_pool=50_000_00,
            overrun_total=0,
            net_savings=50_000_00,
        )
    )

    assert conclusion.headline == "Месяц сейчас в минусе после расходов."
    assert "закрыть минус 30 000 ₽" in (conclusion.details or "")
    assert _codes(conclusion)[0] == "negative_cashflow"
    assert _insight(conclusion, "savings_available").severity == MonthInsightSeverity.ATTENTION
    assert "реальный cashflow сейчас в минусе" in _insight(conclusion, "savings_available").message


def test_expense_month_without_income_gets_data_caveat() -> None:
    conclusion = build_month_conclusion(_report(total_amount=75_000_00, income_total=0))

    assert conclusion.headline == "Месяц: расходы есть, доходы ещё не внесены."
    assert _codes(conclusion)[0] == "income_missing"
    assert "доходы за месяц ещё не внесены" in _insight(conclusion, "income_missing").message


def test_limit_thresholds_are_prioritized() -> None:
    conclusion = build_month_conclusion(
        _report(
            total_amount=150_000_00,
            income_total=250_000_00,
            budget_risks=(
                _limit_line("restaurants_cafes", "Рестораны/Кафе", 6, 45_000_00, 40_000_00),
                _limit_line("auto_transport_taxi", "Авто/Транспорт/Такси", 4, 8_500_00, 10_000_00),
                _limit_line("groceries", "Продукты", 2, 35_000_00, 70_000_00),
            ),
            elapsed_days=10,
            day_count=31,
        ),
        max_insights=8,
    )

    assert _codes(conclusion)[:3] == [
        "limit_overrun:restaurants_cafes",
        "limit_80:auto_transport_taxi",
        "limit_50_early:groceries",
    ]
    assert (
        "превысил лимит на 5 000 ₽"
        in _insight(conclusion, "limit_overrun:restaurants_cafes").message
    )
    assert "уже 85,0% лимита" in _insight(conclusion, "limit_80:auto_transport_taxi").message
    assert "на 10 день месяца" in _insight(conclusion, "limit_50_early:groceries").message


def test_exactly_reached_limit_is_not_reported_as_zero_overrun() -> None:
    conclusion = build_month_conclusion(
        _report(
            total_amount=100_000_00,
            income_total=180_000_00,
            budget_risks=(
                _limit_line("restaurants_cafes", "Рестораны/Кафе", 6, 40_000_00, 40_000_00),
            ),
        ),
        max_insights=8,
    )

    assert "limit_reached:restaurants_cafes" in _codes(conclusion)
    assert "limit_overrun:restaurants_cafes" not in _codes(conclusion)
    assert (
        "превысил лимит на 0 ₽"
        not in _insight(
            conclusion,
            "limit_reached:restaurants_cafes",
        ).message
    )


def test_scoped_report_suppresses_budget_and_savings_insights() -> None:
    conclusion = build_month_conclusion(
        _report(
            scope=TransactionScope.SALON,
            total_amount=90_000_00,
            income_total=70_000_00,
            budget_risks=(
                _limit_line("restaurants_cafes", "Рестораны/Кафе", 6, 45_000_00, 40_000_00),
            ),
            net_savings=-20_000_00,
        )
    )

    assert conclusion.headline == "Салон сейчас в минусе после расходов."
    assert (
        conclusion.details == "Лимиты и копилка считаются только в общем отчёте по всем контурам."
    )
    assert "limit_overrun:restaurants_cafes" not in _codes(conclusion)
    assert "savings_negative" not in _codes(conclusion)


def test_previous_month_category_growth_and_salon_snapshot_can_add_insights() -> None:
    conclusion = build_month_conclusion(
        _report(total_amount=150_000_00, income_total=230_000_00),
        category_changes=(
            CategoryChange(
                code="restaurants_cafes",
                title="Рестораны/Кафе",
                current_amount=60_000_00,
                previous_amount=30_000_00,
                delta_amount=30_000_00,
                delta_percent=100.0,
            ),
        ),
        scope_snapshots=(
            ScopeSnapshot(
                scope=TransactionScope.SALON,
                expenses=70_000_00,
                income=50_000_00,
                net_after_expenses=-20_000_00,
            ),
        ),
        max_insights=8,
    )

    assert "category_growth:restaurants_cafes" in _codes(conclusion)
    assert "salon_negative_cashflow" in _codes(conclusion)
    assert (
        "выше прошлого месяца на 30 000 ₽"
        in _insight(conclusion, "category_growth:restaurants_cafes").message
    )


def test_salon_snapshot_with_expenses_and_no_income_gets_attention() -> None:
    conclusion = build_month_conclusion(
        _report(total_amount=150_000_00, income_total=230_000_00),
        scope_snapshots=(
            ScopeSnapshot(
                scope=TransactionScope.SALON,
                expenses=70_000_00,
                income=0,
                net_after_expenses=-70_000_00,
            ),
        ),
        max_insights=8,
    )

    assert "salon_negative_cashflow" in _codes(conclusion)
    assert (
        "Салон пока в минусе на 70 000 ₽."
        in _insight(
            conclusion,
            "salon_negative_cashflow",
        ).message
    )


def test_auto_accounting_quality_uses_safe_aggregate_counts() -> None:
    conclusion = build_month_conclusion(
        _report(total_amount=80_000_00, income_total=150_000_00),
        auto_accounting_quality=AutoAccountingQuality(
            pending_confirmation_count=2,
            unknown_event_count=1,
            failed_telegram_notification_count=1,
            unsent_pending_count=3,
        ),
        max_insights=8,
    )

    assert _codes(conclusion)[:4] == [
        "bank_delivery_failed",
        "bank_pending_confirmations",
        "bank_unknown_events",
        "bank_unsent_pending",
    ]
    assert "SMS неизвестного формата: 1" in _insight(conclusion, "bank_unknown_events").message


def test_max_insights_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_insights"):
        build_month_conclusion(_report(), max_insights=0)


def _codes(conclusion) -> list[str]:
    return [item.code for item in conclusion.insights]


def _insight(conclusion, code: str):
    return next(item for item in conclusion.insights if item.code == code)


def _report(
    *,
    scope: TransactionScope | None = None,
    total_amount: int = 100_000_00,
    income_total: int = 150_000_00,
    budget_risks: tuple[BudgetLimitLine, ...] = (),
    under_budget_pool: int = 20_000_00,
    overrun_total: int = 0,
    net_savings: int | None = None,
    elapsed_days: int = 20,
    day_count: int = 31,
) -> MonthReport:
    timezone = ZoneInfo("Asia/Barnaul")
    period = Period(
        kind=PeriodKind.MONTH,
        start_at=datetime(2026, 7, 1, tzinfo=timezone),
        end_at=datetime(2026, 8, 1, tzinfo=timezone),
        label="Июль 2026",
    )
    resolved_net_savings = under_budget_pool - overrun_total if net_savings is None else net_savings
    total = total_amount
    income = income_total
    return MonthReport(
        period=period,
        currency="RUB",
        scope=scope,
        total_amount=total,
        income_total=income,
        net_after_expenses=income - total,
        pace=MonthPace(
            elapsed_days=elapsed_days,
            day_count=day_count,
            average_per_day=total // elapsed_days if elapsed_days else 0,
            forecast_amount=total,
        ),
        by_payer=(
            PayerReportLine(
                role="husband", amount=total // 2, share_percent=50.0 if total else 0.0
            ),
            PayerReportLine(
                role="wife", amount=total - total // 2, share_percent=50.0 if total else 0.0
            ),
        ),
        top_categories=(
            CategoryReportLine(
                code="restaurants_cafes",
                title="Рестораны/Кафе",
                owner_role="system",
                sort_order=6,
                amount=total,
                share_percent=100.0 if total else 0.0,
            ),
        )
        if total
        else (),
        other_categories_count=0,
        other_categories_amount=0,
        income_by_recipient=(
            IncomeRecipientLine(
                role="husband", amount=income, share_percent=100.0 if income else 0.0
            ),
        )
        if income
        else (),
        top_income_categories=(
            IncomeCategoryLine(
                code="income_salary",
                title="Зарплата",
                amount=income,
                share_percent=100.0 if income else 0.0,
            ),
        )
        if income
        else (),
        other_income_categories_count=0,
        other_income_categories_amount=0,
        budget_risks=budget_risks,
        no_limit_lines=(
            BudgetNoLimitLine(
                code="taxes",
                title="Налоги",
                sort_order=17,
                spent_amount=12_000_00,
            ),
        )
        if scope is None and total
        else (),
        savings_target_lines=(
            BudgetSavingsTargetLine(
                code="investments_savings",
                title="Инвестиции/Накопления",
                sort_order=15,
                actual_amount=10_000_00,
                target_amount=30_000_00,
                delta_amount=-20_000_00,
                usage_percent=33.3,
            ),
        )
        if scope is None and total
        else (),
        under_budget_pool=under_budget_pool if scope is None else 0,
        overrun_total=overrun_total if scope is None else 0,
        net_savings=resolved_net_savings if scope is None else 0,
        budget=BudgetReport(
            period=period,
            currency="RUB",
            limit_lines=budget_risks,
            no_limit_lines=(),
            savings_target_lines=(),
            under_budget_pool=under_budget_pool,
            overrun_total=overrun_total,
            net_savings=resolved_net_savings,
        ),
    )


def _limit_line(
    code: str,
    title: str,
    sort_order: int,
    spent_amount: int,
    limit_amount: int,
) -> BudgetLimitLine:
    usage = round(spent_amount / limit_amount * 100, 1)
    return BudgetLimitLine(
        code=code,
        title=title,
        sort_order=sort_order,
        spent_amount=spent_amount,
        limit_amount=limit_amount,
        usage_percent=usage,
        remaining_amount=limit_amount - spent_amount,
    )
