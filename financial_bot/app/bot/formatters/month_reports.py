from financial_bot.app.domain.accounting_scope import scope_filter_label, scope_label
from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.domain.monthly_insights import (
    MonthConclusion,
    ScopeSnapshot,
    build_month_conclusion,
)
from financial_bot.app.domain.types import UserRole
from financial_bot.app.services.month_report_service import MonthReport
from financial_bot.app.services.smart_month_summary_service import SmartMonthSummary
from financial_bot.app.services.spending_limit_service import BudgetSavingsTargetLine

ROLE_LABELS = {
    UserRole.HUSBAND.value: "Муж",
    UserRole.WIFE.value: "Жена",
}


def format_month_report(report: MonthReport) -> str:
    return _format_summary(
        report=report,
        conclusion=build_month_conclusion(report),
        scope_snapshots=(),
    )


def format_smart_month_summary(summary: SmartMonthSummary) -> str:
    return _format_summary(
        report=summary.report,
        conclusion=summary.conclusion,
        scope_snapshots=summary.scope_snapshots,
    )


def _format_summary(
    *,
    report: MonthReport,
    conclusion: MonthConclusion,
    scope_snapshots: tuple[ScopeSnapshot, ...],
) -> str:
    lines = [
        f"Итог месяца: {report.period.label}",
        f"Контур: {scope_filter_label(report.scope)}",
        "",
    ]

    if not report.has_activity:
        lines.extend(
            [
                "Вывод",
                conclusion.headline,
                "",
                "Что важно",
            ]
        )
        if conclusion.insights:
            lines.extend(
                f"{index}. {insight.message}"
                for index, insight in enumerate(conclusion.insights, start=1)
            )
        lines.append(
            f"{len(conclusion.insights) + 1}. "
            "Когда появятся расходы или доходы, бот соберёт полный итог месяца."
        )
        return "\n".join(lines)

    lines.extend(_headline_block(report))
    lines.extend(["", "Вывод", conclusion.headline])
    if conclusion.details:
        lines.append(conclusion.details)

    if conclusion.insights:
        lines.extend(["", "Что важно"])
        lines.extend(
            f"{index}. {insight.message}"
            for index, insight in enumerate(conclusion.insights, start=1)
        )

    if report.top_categories:
        lines.extend(["", "Расходы по категориям"])
        lines.extend(
            f"{index}. {line.title} — {_money(line.amount, report.currency)} "
            f"({_percent(line.share_percent)})"
            for index, line in enumerate(report.top_categories, start=1)
        )
        if report.other_categories_count:
            lines.append(
                f"Остальные {report.other_categories_count} "
                f"{_category_word(report.other_categories_count)} — "
                f"{_money(report.other_categories_amount, report.currency)}"
            )

    if report.top_income_categories:
        lines.extend(["", "Доходы по источникам"])
        lines.extend(
            f"{index}. {line.title} — {_money(line.amount, report.currency)} "
            f"({_percent(line.share_percent)})"
            for index, line in enumerate(report.top_income_categories, start=1)
        )
        if report.other_income_categories_count:
            lines.append(
                f"Остальные {report.other_income_categories_count} "
                f"{_category_word(report.other_income_categories_count)} дохода — "
                f"{_money(report.other_income_categories_amount, report.currency)}"
            )

    if scope_snapshots:
        lines.extend(["", "Дом и Салон"])
        lines.extend(
            _format_scope_snapshot(snapshot, report.currency) for snapshot in scope_snapshots
        )

    if report.scope is None:
        lines.extend(["", "Лимиты и резерв"])
    if report.scope is None and report.has_expenses:
        lines.append(f"Свободно в лимитах: {_money(report.under_budget_pool, report.currency)}")
        lines.append(f"Превышения: {_money(report.overrun_total, report.currency)}")
        lines.append(_format_net_savings(report))
        if report.savings_target_lines:
            lines.extend(
                _format_savings_target(line, report.currency)
                for line in report.savings_target_lines
            )
        if report.no_limit_lines:
            no_limit_total = sum(line.spent_amount for line in report.no_limit_lines)
            lines.append(f"Без лимита: {_money(no_limit_total, report.currency)}")
    elif report.scope is None:
        lines.append("Расходов пока нет, оценка резерва появится позже.")

    if report.has_expenses:
        lines.extend(["", "Кто платил"])
        lines.extend(
            f"{ROLE_LABELS.get(line.role, line.role)} — {_money(line.amount, report.currency)} "
            f"({_percent(line.share_percent)})"
            for line in report.by_payer
        )

    if report.has_income:
        lines.extend(["", "Кому пришли доходы"])
        lines.extend(
            f"{ROLE_LABELS.get(line.role, line.role)} — {_money(line.amount, report.currency)} "
            f"({_percent(line.share_percent)})"
            for line in report.income_by_recipient
            if line.amount > 0
        )

    return "\n".join(lines)


def _headline_block(report: MonthReport) -> list[str]:
    lines = [
        "Главное",
        f"День месяца: {report.pace.elapsed_days} из {report.pace.day_count}",
        f"Доходы: {_money(report.income_total, report.currency)}",
        f"Расходы: {_money(report.total_amount, report.currency)}",
        f"После расходов: {_signed_money(report.net_after_expenses, report.currency)}",
    ]
    if report.has_expenses:
        lines.extend(
            [
                f"Темп расходов: {_money(report.pace.average_per_day, report.currency)}/день",
                f"Прогноз расходов: {_money(report.pace.forecast_amount, report.currency)}",
            ]
        )
    return lines


def _format_scope_snapshot(snapshot: ScopeSnapshot, currency: str) -> str:
    label = scope_label(snapshot.scope)
    if not snapshot.has_activity:
        return f"{label}: данных за месяц пока нет."

    line = (
        f"{label}: расходы {_money(snapshot.expenses, currency)}, "
        f"доходы {_money(snapshot.income, currency)}, "
        f"итог {_signed_money(snapshot.net_after_expenses, currency)}"
    )
    if snapshot.top_category_title:
        line = f"{line}; крупная категория: {snapshot.top_category_title}"
    return f"{line}."


def _format_savings_target(line: BudgetSavingsTargetLine, currency: str) -> str:
    base = (
        f"{line.title}: внесено {_money(line.actual_amount, currency)} из "
        f"{_money(line.target_amount, currency)}"
    )
    if line.delta_amount >= 0:
        return f"{base}; выше цели на {_money(line.delta_amount, currency)}"
    return f"{base}; не хватает {_money(abs(line.delta_amount), currency)}"


def _format_net_savings(report: MonthReport) -> str:
    amount = report.net_savings
    currency = report.currency
    if amount >= 0:
        if report.has_income and report.net_after_expenses < 0:
            return "Свободный резерв есть по лимитам, но реальный cashflow сейчас в минусе."
        return f"Можно отложить по лимитам: {_money(amount, currency)}"
    return f"Нужно компенсировать перерасход: {_money(abs(amount), currency)}"


def _signed_money(amount_minor: int, currency: str) -> str:
    if amount_minor < 0:
        return f"-{_money(abs(amount_minor), currency)}"
    return f"+{_money(amount_minor, currency)}"


def _money(amount_minor: int, currency: str) -> str:
    return format_money_minor(round_minor_to_whole_units_minor(amount_minor), currency)


def _percent(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")


def _category_word(count: int) -> str:
    if 11 <= count % 100 <= 14:
        return "категорий"
    if count % 10 == 1:
        return "категория"
    if count % 10 in {2, 3, 4}:
        return "категории"
    return "категорий"
