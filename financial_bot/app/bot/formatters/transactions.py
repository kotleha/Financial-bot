from datetime import datetime

from financial_bot.app.domain.money import format_money_minor
from financial_bot.app.domain.types import UserRole
from financial_bot.app.services.transaction_service import CreatedTransactionSummary

ROLE_LABELS = {
    UserRole.HUSBAND.value: "Муж",
    UserRole.WIFE.value: "Жена",
}


def format_transaction_created(summary: CreatedTransactionSummary) -> str:
    return "\n".join(
        [
            "Записал:",
            f"{format_money_minor(summary.amount, summary.currency)} — {summary.category_title}",
            f"Оплатил: {ROLE_LABELS.get(summary.payer_role, summary.payer_role)}",
            f"Дата: {_format_date(summary.occurred_at)}",
        ]
    )


def format_income_created(summary: CreatedTransactionSummary) -> str:
    return "\n".join(
        [
            "Учёл доход:",
            f"{format_money_minor(summary.amount, summary.currency)} — {summary.category_title}",
            f"Получатель: {ROLE_LABELS.get(summary.payer_role, summary.payer_role)}",
            f"Дата: {_format_date(summary.occurred_at)}",
        ]
    )


def format_transaction_updated(summary: CreatedTransactionSummary) -> str:
    return "\n".join(["Обновил:", _format_transaction_brief(summary)])


def format_transaction_deleted(summary: CreatedTransactionSummary) -> str:
    return "\n".join(["Удалил:", _format_transaction_brief(summary)])


def format_transaction_repeated(summary: CreatedTransactionSummary) -> str:
    return "\n".join(["Повторил:", _format_transaction_brief(summary)])


def format_transaction_for_edit(summary: CreatedTransactionSummary) -> str:
    return "\n".join(["Последняя операция:", _format_transaction_brief(summary)])


def _format_transaction_brief(summary: CreatedTransactionSummary) -> str:
    return "\n".join(
        [
            f"{format_money_minor(summary.amount, summary.currency)} — {summary.category_title}",
            f"Оплатил: {ROLE_LABELS.get(summary.payer_role, summary.payer_role)}",
            f"Дата: {_format_date(summary.occurred_at)}",
        ]
    )


def _format_date(value: datetime) -> str:
    return value.strftime("%d.%m.%Y")
