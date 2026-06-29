from financial_bot.app.domain.money import format_money_minor
from financial_bot.app.domain.spending_limits import LimitRuleKind
from financial_bot.app.services.spending_limit_service import (
    BudgetLimitLine,
    BudgetReport,
    BudgetSavingsTargetLine,
    LimitOverview,
    LimitOverviewLine,
    SpendingLimitThresholdAlert,
)


def format_budget_report(report: BudgetReport) -> str:
    lines = [f"Бюджет за {report.period.label}", ""]

    lines.append("Категории:")
    lines.extend(_format_limit_line(line, report.currency) for line in report.limit_lines)

    if report.no_limit_lines:
        lines.extend(["", "Без лимита:"])
        lines.extend(
            f"{line.title} — {format_money_minor(line.spent_amount, report.currency)}"
            for line in report.no_limit_lines
        )

    if report.savings_target_lines:
        lines.extend(["", "Инвестиции/Накопления:"])
        lines.extend(
            _format_savings_target_line(line, report.currency)
            for line in report.savings_target_lines
        )

    lines.extend(
        [
            "",
            f"Итого недотратили: {format_money_minor(report.under_budget_pool, report.currency)}",
            f"Итого превысили: {format_money_minor(report.overrun_total, report.currency)}",
            (
                "Можно отложить в копилку: "
                f"{_format_signed_money(report.net_savings, report.currency)}"
            ),
        ]
    )
    return "\n".join(lines)


def format_limits_overview(overview: LimitOverview) -> str:
    lines = [f"Лимиты на {overview.period.label}", ""]
    lines.extend(_format_limit_overview_line(line, overview.currency) for line in overview.lines)
    lines.extend(
        [
            "",
            "Изменить:",
            "/limits set 2 70000",
            "/limits off 17",
            "/limits target 15 30000",
            "/limits utilities summer 8000 winter 15000",
        ]
    )
    return "\n".join(lines)


def format_savings_report(report: BudgetReport) -> str:
    lines = [
        f"Копилка за {report.period.label}",
        "",
        f"Итого недотратили: {format_money_minor(report.under_budget_pool, report.currency)}",
        f"Итого превысили: {format_money_minor(report.overrun_total, report.currency)}",
        f"Должно остаться: {_format_signed_money(report.net_savings, report.currency)}",
    ]

    overruns = [line for line in report.limit_lines if line.remaining_amount < 0]
    if overruns:
        lines.extend(["", "Превышения:"])
        lines.extend(
            f"{line.title} — {format_money_minor(line.overrun_amount, report.currency)}"
            for line in overruns
        )

    positive_remaining = [line for line in report.limit_lines if line.remaining_amount > 0]
    if positive_remaining:
        top_remaining = sorted(
            positive_remaining,
            key=lambda line: line.remaining_amount,
            reverse=True,
        )[:5]
        lines.extend(["", "Крупные остатки:"])
        lines.extend(
            f"{line.title} — {format_money_minor(line.remaining_amount, report.currency)}"
            for line in top_remaining
        )

    if report.savings_target_lines:
        lines.extend(["", "Цель накоплений:"])
        lines.extend(
            _format_savings_target_line(line, report.currency)
            for line in report.savings_target_lines
        )

    return "\n".join(lines)


def format_threshold_alert(alert: SpendingLimitThresholdAlert, currency: str) -> str:
    if alert.remaining_amount >= 0:
        return "\n".join(
            [
                f"Лимит: {alert.category_title}",
                (
                    f"Потрачено {format_money_minor(alert.spent_amount, currency)} "
                    f"из {format_money_minor(alert.limit_amount, currency)}."
                ),
                f"Использовано: {_format_percent(alert.usage_percent)}.",
                f"Осталось: {format_money_minor(alert.remaining_amount, currency)}.",
            ]
        )

    return "\n".join(
        [
            f"Лимит превышен: {alert.category_title}",
            (
                f"Потрачено {format_money_minor(alert.spent_amount, currency)} "
                f"из {format_money_minor(alert.limit_amount, currency)}."
            ),
            f"Использовано: {_format_percent(alert.usage_percent)}.",
            f"Превышение: {format_money_minor(alert.overrun_amount, currency)}.",
        ]
    )


def _format_limit_line(line: BudgetLimitLine, currency: str) -> str:
    base = (
        f"{line.title} — {format_money_minor(line.spent_amount, currency)} "
        f"из {format_money_minor(line.limit_amount, currency)} "
        f"({_format_percent(line.usage_percent)})"
    )
    if line.remaining_amount >= 0:
        return f"{base}; осталось {format_money_minor(line.remaining_amount, currency)}"
    return f"{base}; превышение {format_money_minor(line.overrun_amount, currency)}"


def _format_limit_overview_line(line: LimitOverviewLine, currency: str) -> str:
    return (
        f"{line.sort_order}. {line.title} — "
        f"{format_limit_rule_label(line.kind, line.amount, currency)}"
    )


def format_limit_rule_label(
    kind: LimitRuleKind,
    amount: int | None,
    currency: str,
) -> str:
    match kind:
        case LimitRuleKind.MONTHLY_LIMIT | LimitRuleKind.SEASONAL_LIMIT:
            if amount is None:
                return "лимит не задан"
            return format_money_minor(amount, currency)
        case LimitRuleKind.SAVINGS_TARGET:
            if amount is None:
                return "цель не задана"
            return f"цель {format_money_minor(amount, currency)}"
        case LimitRuleKind.NO_LIMIT:
            return "без лимита"
    return kind.value


def _format_savings_target_line(line: BudgetSavingsTargetLine, currency: str) -> str:
    base = (
        f"Цель {format_money_minor(line.target_amount, currency)}, "
        f"факт {format_money_minor(line.actual_amount, currency)} "
        f"({_format_percent(line.usage_percent)})"
    )
    if line.delta_amount >= 0:
        return f"{base}; перевыполнено на {format_money_minor(line.delta_amount, currency)}"
    return f"{base}; не хватает {format_money_minor(abs(line.delta_amount), currency)}"


def _format_signed_money(amount: int, currency: str) -> str:
    if amount < 0:
        return f"-{format_money_minor(abs(amount), currency)}"
    return format_money_minor(amount, currency)


def _format_percent(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")
