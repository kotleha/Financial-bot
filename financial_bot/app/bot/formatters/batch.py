from financial_bot.app.domain.money import format_money_minor
from financial_bot.app.services.transaction_service import BatchCreateResult


def format_batch_created(result: BatchCreateResult, currency: str) -> str:
    lines: list[str] = []
    if result.created:
        lines.append(f"Добавлено {len(result.created)} операции:")
        lines.append("")
        for index, summary in enumerate(result.created, start=1):
            amount = format_money_minor(summary.amount, summary.currency)
            lines.append(f"{index}. {amount} — {summary.category_title}")
        lines.append("")
        lines.append(f"Итого: {format_money_minor(result.total_amount, currency)}")

    if result.errors:
        if lines:
            lines.append("")
        lines.append("Не удалось разобрать:")
        for error in result.errors:
            lines.append(f"{error.line_number}. {error.raw_line}")

    return "\n".join(lines)
