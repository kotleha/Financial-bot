from financial_bot.app.domain.accounting_scope import scope_label
from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.services.month_close_service import (
    MonthCloseChecklistItem,
    MonthCloseItemStatus,
    MonthCloseReport,
)


def format_month_close_report(report: MonthCloseReport) -> str:
    monthly = report.summary.report
    lines = [
        f"Закрытие месяца: {monthly.period.label}",
        "",
        "Готовность",
        _readiness_line(report),
        "",
        "Чеклист",
    ]
    lines.extend(_format_checklist_item(item) for item in report.checklist)

    lines.extend(
        [
            "",
            "Финальный ориентир",
            f"Доходы: {_money(monthly.income_total, monthly.currency)}",
            f"Расходы: {_money(monthly.total_amount, monthly.currency)}",
            f"После расходов: {_signed_money(monthly.net_after_expenses, monthly.currency)}",
            _budget_line(report),
        ]
    )

    if report.summary.scope_snapshots:
        lines.extend(["", "Дом и Салон"])
        for snapshot in report.summary.scope_snapshots:
            if not snapshot.has_activity:
                lines.append(f"{scope_label(snapshot.scope)}: данных пока нет.")
                continue
            lines.append(
                f"{scope_label(snapshot.scope)}: расходы "
                f"{_money(snapshot.expenses, monthly.currency)}, доходы "
                f"{_money(snapshot.income, monthly.currency)}, итог "
                f"{_signed_money(snapshot.net_after_expenses, monthly.currency)}"
            )

    lines.extend(
        [
            "",
            "Дальше",
            "Кнопки ниже открывают дашборд, ожидающие банковские операции и полный итог месяца.",
        ]
    )
    return "\n".join(lines)


def _readiness_line(report: MonthCloseReport) -> str:
    if report.has_blockers:
        return (
            f"Сначала нужно разобрать критичные пункты: {report.blocked_count}. "
            f"Ещё стоит проверить: {report.attention_count}."
        )
    if report.attention_count:
        return (
            "Критичных блокеров нет, но перед финальным итогом стоит проверить "
            f"{report.attention_count} пункт(а)."
        )
    return "Месяц выглядит готовым к финальному итогу."


def _format_checklist_item(item: MonthCloseChecklistItem) -> str:
    return f"{_status_icon(item.status)} {item.title}: {item.message}"


def _status_icon(status: MonthCloseItemStatus) -> str:
    if status == MonthCloseItemStatus.BLOCKED:
        return "⛔"
    if status == MonthCloseItemStatus.ATTENTION:
        return "⚠️"
    return "✅"


def _budget_line(report: MonthCloseReport) -> str:
    monthly = report.summary.report
    if not monthly.has_expenses:
        return "Резерв по лимитам: появится после расходов"
    if monthly.net_savings < 0:
        return f"Резерв по лимитам: -{_money(abs(monthly.net_savings), monthly.currency)}"
    return f"Резерв по лимитам: +{_money(monthly.net_savings, monthly.currency)}"


def _signed_money(amount_minor: int, currency: str) -> str:
    if amount_minor < 0:
        return f"-{_money(abs(amount_minor), currency)}"
    return f"+{_money(amount_minor, currency)}"


def _money(amount_minor: int, currency: str) -> str:
    return format_money_minor(round_minor_to_whole_units_minor(amount_minor), currency)
