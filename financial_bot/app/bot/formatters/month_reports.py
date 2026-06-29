from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.domain.types import UserRole
from financial_bot.app.services.month_report_service import MonthReport
from financial_bot.app.services.spending_limit_service import (
    BudgetLimitLine,
    BudgetSavingsTargetLine,
)

ROLE_LABELS = {
    UserRole.HUSBAND.value: "Муж",
    UserRole.WIFE.value: "Жена",
}


def format_month_report(report: MonthReport) -> str:
    lines = [f"Итог месяца: {report.period.label}", ""]

    if not report.has_activity:
        lines.extend(
            [
                "Данных за месяц пока нет.",
                "Когда появятся расходы или доходы, здесь будет короткий финансовый вывод.",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "Главное",
            f"День месяца: {report.pace.elapsed_days} из {report.pace.day_count}",
            f"Доходы: {_money(report.income_total, report.currency)}",
            f"Расходы: {_money(report.total_amount, report.currency)}",
            f"После расходов: {_signed_money(report.net_after_expenses, report.currency)}",
        ]
    )

    if report.has_expenses:
        lines.extend(
            [
                f"Темп расходов: {_money(report.pace.average_per_day, report.currency)}/день",
                f"Прогноз расходов: {_money(report.pace.forecast_amount, report.currency)}",
            ]
        )

    lines.extend(["", "Коротко", _format_plain_summary(report)])

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

    if report.has_expenses:
        lines.extend(["", "Лимиты и резерв"])
        lines.append(f"Свободно в лимитах: {_money(report.under_budget_pool, report.currency)}")
        lines.append(f"Превышения: {_money(report.overrun_total, report.currency)}")
        lines.append(_format_net_savings(report.net_savings, report.currency))
    else:
        lines.extend(["", "Лимиты и резерв", "Расходов пока нет, оценка резерва появится позже."])

    if report.has_expenses and report.budget_risks:
        lines.extend(["", "Под вниманием"])
        lines.extend(_format_budget_risk(line, report.currency) for line in report.budget_risks)

    if report.has_expenses and report.no_limit_lines:
        lines.extend(["", "Без лимита"])
        lines.extend(
            f"{line.title} — {_money(line.spent_amount, report.currency)}"
            for line in report.no_limit_lines
        )

    if report.has_expenses and report.savings_target_lines:
        lines.extend(["", "Накопления"])
        lines.extend(
            _format_savings_target(line, report.currency) for line in report.savings_target_lines
        )

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


def _format_budget_risk(line: BudgetLimitLine, currency: str) -> str:
    base = (
        f"{line.title} — {_money(line.spent_amount, currency)} из "
        f"{_money(line.limit_amount, currency)} ({_percent(line.usage_percent)})"
    )
    if line.remaining_amount >= 0:
        return f"{base}; осталось {_money(line.remaining_amount, currency)}"
    return f"{base}; превышение {_money(line.overrun_amount, currency)}"


def _format_savings_target(line: BudgetSavingsTargetLine, currency: str) -> str:
    base = (
        f"{line.title} — внесено {_money(line.actual_amount, currency)} из "
        f"{_money(line.target_amount, currency)}"
    )
    if line.delta_amount >= 0:
        return f"{base}; выше цели на {_money(line.delta_amount, currency)}"
    return f"{base}; не хватает {_money(abs(line.delta_amount), currency)}"


def _format_net_savings(amount: int, currency: str) -> str:
    if amount >= 0:
        return f"Можно отложить по лимитам: {_money(amount, currency)}"
    return f"Нужно компенсировать перерасход: {_money(abs(amount), currency)}"


def _format_plain_summary(report: MonthReport) -> str:
    if report.has_income and not report.has_expenses:
        cashflow_part = (
            f"доходы внесены, расходов пока нет: +{_money(report.income_total, report.currency)}"
        )
    elif report.has_income and report.net_after_expenses >= 0:
        cashflow_part = (
            f"месяц пока в плюсе на {_money(report.net_after_expenses, report.currency)}"
        )
    elif report.has_income:
        cashflow_part = (
            f"расходы выше доходов на {_money(abs(report.net_after_expenses), report.currency)}"
        )
    elif report.has_expenses:
        cashflow_part = "доходы за месяц ещё не внесены, поэтому остаток неполный"
    else:
        cashflow_part = "расходы ещё не внесены"

    if not report.has_expenses:
        budget_part = "лимитный резерв появится после первых расходов"
    elif report.overrun_total > 0:
        budget_part = (
            f"превышения уже съели {_money(report.overrun_total, report.currency)} "
            "из свободных лимитов"
        )
    elif report.net_savings > 0:
        budget_part = f"по лимитам можно отложить до {_money(report.net_savings, report.currency)}"
    else:
        budget_part = "по лимитам пока нет запаса для копилки"

    return f"{cashflow_part}; {budget_part}."


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
