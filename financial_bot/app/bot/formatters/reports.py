from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.domain.types import UserRole
from financial_bot.app.services.report_service import PeriodReport

ROLE_LABELS = {
    UserRole.HUSBAND.value: "Муж",
    UserRole.WIFE.value: "Жена",
}


def format_period_report(report: PeriodReport) -> str:
    lines = [
        report.period.label,
        "",
        f"Фактические расходы: {_format_report_money(report.total_amount, report.currency)}",
    ]

    if report.total_amount == 0:
        lines.extend(["", "За период расходов нет."])
        return "\n".join(lines)

    lines.extend(["", "По плательщику:"])
    lines.extend(
        f"{ROLE_LABELS.get(item.role, item.role)} — "
        f"{_format_report_money(item.amount, report.currency)} — "
        f"{_format_percent(item.share_percent)}"
        for item in report.by_payer
    )

    if report.by_category:
        lines.extend(["", "Категории:"])
        lines.extend(
            f"{item.title} — {_format_report_money(item.amount, report.currency)}"
            for item in report.by_category
        )

    return "\n".join(lines)


def _format_report_money(amount_minor: int, currency: str) -> str:
    return format_money_minor(round_minor_to_whole_units_minor(amount_minor), currency)


def _format_percent(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")
