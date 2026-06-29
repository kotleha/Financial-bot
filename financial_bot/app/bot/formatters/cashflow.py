from financial_bot.app.bot.formatters.context_hints import BUDGET_SAVINGS_HINT, INCOME_REPORT_HINT
from financial_bot.app.bot.formatters.reports import ROLE_LABELS
from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.services.cashflow_service import CashflowReport


def format_cashflow_report(report: CashflowReport) -> str:
    lines = [
        f"Денежный поток за {report.period.label}",
        "",
        f"Доходы: {_format_money(report.income_total, report.currency)}",
        f"Расходы: {_format_money(report.expense_total, report.currency)}",
        f"Итог после расходов: {_format_signed_money(report.net_after_expenses, report.currency)}",
    ]

    if report.income_total > 0:
        lines.extend(["", "Доходы по источникам:"])
        lines.extend(
            f"{line.title} — {_format_money(line.amount, report.currency)} — "
            f"{_format_percent(line.share_percent)}"
            for line in report.income_by_category
        )

        lines.extend(["", "Доходы по получателю:"])
        lines.extend(
            f"{ROLE_LABELS.get(line.role, line.role)} — "
            f"{_format_money(line.amount, report.currency)} — "
            f"{_format_percent(line.share_percent)}"
            for line in report.income_by_recipient
        )
    else:
        lines.extend(
            [
                "",
                "Доходов за период пока нет.",
                "Банковские поступления можно учесть кнопкой «Учесть доход».",
            ]
        )

    if report.budget_net_savings is not None:
        lines.extend(
            [
                "",
                "Оценка копилки по лимитам:",
                _format_signed_money(report.budget_net_savings, report.currency),
                BUDGET_SAVINGS_HINT,
            ]
        )

    lines.extend(["", INCOME_REPORT_HINT])
    return "\n".join(lines)


def _format_money(amount_minor: int, currency: str) -> str:
    return format_money_minor(round_minor_to_whole_units_minor(amount_minor), currency)


def _format_signed_money(amount_minor: int, currency: str) -> str:
    if amount_minor < 0:
        return f"-{_format_money(abs(amount_minor), currency)}"
    return f"+{_format_money(amount_minor, currency)}"


def _format_percent(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")
