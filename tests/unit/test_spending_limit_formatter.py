from datetime import datetime
from zoneinfo import ZoneInfo

from financial_bot.app.bot.formatters.spending_limits import (
    format_budget_report,
    format_limits_overview,
    format_savings_report,
    format_threshold_alert,
)
from financial_bot.app.domain.periods import Period, PeriodKind
from financial_bot.app.domain.spending_limits import LimitRuleKind
from financial_bot.app.services.spending_limit_service import (
    BudgetLimitLine,
    BudgetNoLimitLine,
    BudgetReport,
    BudgetSavingsTargetLine,
    LimitOverview,
    LimitOverviewLine,
    SpendingLimitThresholdAlert,
)


def test_format_budget_report() -> None:
    timezone = ZoneInfo("Asia/Barnaul")
    report = BudgetReport(
        period=Period(
            kind=PeriodKind.MONTH,
            start_at=datetime(2026, 6, 1, tzinfo=timezone),
            end_at=datetime(2026, 7, 1, tzinfo=timezone),
            label="Июнь 2026",
        ),
        currency="RUB",
        limit_lines=(
            BudgetLimitLine(
                code="groceries",
                title="Продукты",
                sort_order=2,
                spent_amount=7_200_000,
                limit_amount=7_000_000,
                usage_percent=102.9,
                remaining_amount=-200_000,
            ),
            BudgetLimitLine(
                code="restaurants_cafes",
                title="Рестораны/Кафе",
                sort_order=6,
                spent_amount=2_000_000,
                limit_amount=4_000_000,
                usage_percent=50.0,
                remaining_amount=2_000_000,
            ),
        ),
        no_limit_lines=(
            BudgetNoLimitLine(
                code="taxes",
                title="Налоги",
                sort_order=17,
                spent_amount=420_000,
            ),
        ),
        savings_target_lines=(
            BudgetSavingsTargetLine(
                code="investments_savings",
                title="Инвестиции/Накопления",
                sort_order=15,
                actual_amount=1_200_000,
                target_amount=3_000_000,
                delta_amount=-1_800_000,
                usage_percent=40.0,
            ),
        ),
        under_budget_pool=2_000_000,
        overrun_total=200_000,
        net_savings=1_800_000,
    )

    formatted = format_budget_report(report)

    assert "Бюджет за Июнь 2026" in formatted
    assert "Продукты — 72 000 ₽ из 70 000 ₽ (102,9%); превышение 2 000 ₽" in formatted
    assert "Рестораны/Кафе — 20 000 ₽ из 40 000 ₽ (50,0%); осталось 20 000 ₽" in formatted
    assert "Без лимита:" in formatted
    assert "Налоги — 4 200 ₽" in formatted
    assert "Цель 30 000 ₽, факт 12 000 ₽ (40,0%); не хватает 18 000 ₽" in formatted
    assert "Итого недотратили: 20 000 ₽" in formatted
    assert "Итого превысили: 2 000 ₽" in formatted
    assert "Можно отложить в копилку: 18 000 ₽" in formatted


def test_format_limits_overview() -> None:
    timezone = ZoneInfo("Asia/Barnaul")
    overview = LimitOverview(
        period=Period(
            kind=PeriodKind.MONTH,
            start_at=datetime(2026, 6, 1, tzinfo=timezone),
            end_at=datetime(2026, 7, 1, tzinfo=timezone),
            label="Июнь 2026",
        ),
        currency="RUB",
        lines=(
            LimitOverviewLine(
                code="groceries",
                title="Продукты",
                sort_order=2,
                kind=LimitRuleKind.MONTHLY_LIMIT,
                amount=7_000_000,
            ),
            LimitOverviewLine(
                code="investments_savings",
                title="Инвестиции/Накопления",
                sort_order=15,
                kind=LimitRuleKind.SAVINGS_TARGET,
                amount=3_000_000,
            ),
            LimitOverviewLine(
                code="taxes",
                title="Налоги",
                sort_order=17,
                kind=LimitRuleKind.NO_LIMIT,
                amount=None,
            ),
        ),
    )

    formatted = format_limits_overview(overview)

    assert "Лимиты на Июнь 2026" in formatted
    assert "2. Продукты — 70 000 ₽" in formatted
    assert "15. Инвестиции/Накопления — цель 30 000 ₽" in formatted
    assert "17. Налоги — без лимита" in formatted
    assert "/limits set 2 70000" in formatted


def test_format_savings_report_is_short_copilka_summary() -> None:
    report = _sample_budget_report()

    formatted = format_savings_report(report)

    assert "Копилка за Июнь 2026" in formatted
    assert "Должно остаться: 18 000 ₽" in formatted
    assert "Превышения:" in formatted
    assert "Продукты — 2 000 ₽" in formatted
    assert "Крупные остатки:" in formatted
    assert "Рестораны/Кафе — 20 000 ₽" in formatted
    assert "Категории:" not in formatted


def test_format_threshold_alert_before_overrun() -> None:
    alert = SpendingLimitThresholdAlert(
        category_code="groceries",
        category_title="Продукты",
        threshold_percent=80,
        spent_amount=5_600_000,
        limit_amount=7_000_000,
        usage_percent=80.0,
        remaining_amount=1_400_000,
    )

    formatted = format_threshold_alert(alert, "RUB")

    assert "Лимит: Продукты" in formatted
    assert "Потрачено 56 000 ₽ из 70 000 ₽." in formatted
    assert "Использовано: 80,0%." in formatted
    assert "Осталось: 14 000 ₽." in formatted


def test_format_threshold_alert_after_overrun() -> None:
    alert = SpendingLimitThresholdAlert(
        category_code="groceries",
        category_title="Продукты",
        threshold_percent=100,
        spent_amount=7_200_000,
        limit_amount=7_000_000,
        usage_percent=102.9,
        remaining_amount=-200_000,
    )

    formatted = format_threshold_alert(alert, "RUB")

    assert "Лимит превышен: Продукты" in formatted
    assert "Использовано: 102,9%." in formatted
    assert "Превышение: 2 000 ₽." in formatted


def _sample_budget_report() -> BudgetReport:
    timezone = ZoneInfo("Asia/Barnaul")
    return BudgetReport(
        period=Period(
            kind=PeriodKind.MONTH,
            start_at=datetime(2026, 6, 1, tzinfo=timezone),
            end_at=datetime(2026, 7, 1, tzinfo=timezone),
            label="Июнь 2026",
        ),
        currency="RUB",
        limit_lines=(
            BudgetLimitLine(
                code="groceries",
                title="Продукты",
                sort_order=2,
                spent_amount=7_200_000,
                limit_amount=7_000_000,
                usage_percent=102.9,
                remaining_amount=-200_000,
            ),
            BudgetLimitLine(
                code="restaurants_cafes",
                title="Рестораны/Кафе",
                sort_order=6,
                spent_amount=2_000_000,
                limit_amount=4_000_000,
                usage_percent=50.0,
                remaining_amount=2_000_000,
            ),
        ),
        no_limit_lines=(
            BudgetNoLimitLine(
                code="taxes",
                title="Налоги",
                sort_order=17,
                spent_amount=420_000,
            ),
        ),
        savings_target_lines=(
            BudgetSavingsTargetLine(
                code="investments_savings",
                title="Инвестиции/Накопления",
                sort_order=15,
                actual_amount=1_200_000,
                target_amount=3_000_000,
                delta_amount=-1_800_000,
                usage_percent=40.0,
            ),
        ),
        under_budget_pool=2_000_000,
        overrun_total=200_000,
        net_savings=1_800_000,
    )
