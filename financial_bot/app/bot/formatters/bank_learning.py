from datetime import datetime

from financial_bot.app.services.bank_learning_rule_service import (
    BankLearningRuleDetails,
    BankLearningRuleLine,
    BankLearningRuleStatusResult,
    BankLearningRuleUpdateResult,
)


def format_bank_learning_rules_list(rules: tuple[BankLearningRuleLine, ...]) -> str:
    if not rules:
        return (
            "Выученных правил пока нет.\n\n"
            "Они появятся после того, как вы подтвердите банковский расход с продавцом. "
            "После повторного подтверждения бот сможет записывать похожие расходы автоматически."
        )

    active_count = sum(1 for rule in rules if rule.is_active)
    inactive_count = len(rules) - active_count
    lines = [
        "Выученные правила категорий",
        "",
        f"Активные: {active_count}",
        f"Отключённые: {inactive_count}",
        "",
        "Выберите правило, чтобы посмотреть детали или изменить категорию.",
    ]
    return "\n".join(lines)


def format_bank_learning_rule_details(details: BankLearningRuleDetails) -> str:
    status = "активно" if details.is_active else "отключено"
    return "\n".join(
        [
            "Правило автоучёта",
            "",
            f"Банк: {details.bank.upper()}",
            f"Продавец: {details.merchant_display}",
            f"Ключ: {details.merchant_key}",
            f"Категория: {details.category_title}",
            f"Статус: {status}",
            f"Подтверждений: {details.hit_count}",
            f"Последнее подтверждение: {_format_datetime(details.last_confirmed_at)}",
            f"Последнее применение: {_format_datetime(details.last_used_at)}",
            "",
            "Активное правило может записывать похожие расходы автоматически. "
            "Если категория неверная, измените её или отключите правило.",
        ]
    )


def format_bank_learning_rule_category_updated(result: BankLearningRuleUpdateResult) -> str:
    return "\n".join(
        [
            "Обновил правило автоучёта:",
            "",
            f"{result.bank.upper()} · {result.merchant_display}",
            f"Было: {result.old_category_title}",
            f"Стало: {result.new_category_title}",
            "",
            "Правило включено и будет использоваться для следующих похожих SMS.",
        ]
    )


def format_bank_learning_rule_status_updated(result: BankLearningRuleStatusResult) -> str:
    status = "включено" if result.is_active else "отключено"
    suffix = (
        "Бот снова сможет применять эту категорию к похожим SMS."
        if result.is_active
        else "Бот больше не будет автоматически применять это правило."
    )
    return "\n".join(
        [
            f"Правило {status}:",
            "",
            f"{result.bank.upper()} · {result.merchant_display} → {result.category_title}",
            "",
            suffix,
        ]
    )


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "ещё не было"
    return value.strftime("%d.%m.%Y %H:%M")
