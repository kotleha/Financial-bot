from datetime import datetime

from financial_bot.app.bot.formatters.context_hints import LEARNING_RULE_MANAGEMENT_HINT
from financial_bot.app.domain.types import BankCategoryRuleMode
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

    autosave_count = sum(1 for rule in rules if rule.mode == BankCategoryRuleMode.AUTOSAVE)
    suggest_count = sum(1 for rule in rules if rule.mode == BankCategoryRuleMode.SUGGEST)
    disabled_count = sum(1 for rule in rules if rule.mode == BankCategoryRuleMode.DISABLED)
    lines = [
        "Выученные правила категорий",
        "",
        f"Автосохранение: {autosave_count}",
        f"Только подсказки: {suggest_count}",
        f"Отключённые: {disabled_count}",
        "",
        "Выберите правило, чтобы посмотреть, почему бот выбирает категорию, и изменить режим.",
        LEARNING_RULE_MANAGEMENT_HINT,
    ]
    return "\n".join(lines)


def format_bank_learning_rule_details(details: BankLearningRuleDetails) -> str:
    mode_label = _mode_label(details.mode)
    return "\n".join(
        [
            "Правило автоучёта",
            "",
            f"Банк: {details.bank.upper()}",
            f"Продавец: {details.merchant_display}",
            f"Ключ: {details.merchant_key}",
            f"Категория: {details.category_title}",
            f"Режим: {mode_label}",
            f"Подтверждений: {details.hit_count}",
            f"Последнее подтверждение: {_format_datetime(details.last_confirmed_at)}",
            f"Последнее применение: {_format_datetime(details.last_used_at)}",
            "",
            _mode_explanation(details.mode, hit_count=details.hit_count),
            "Правило работает только для похожего продавца в этом банке.",
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
            f"Режим: {_mode_label(result.mode)}",
            "",
            _mode_explanation(result.mode, hit_count=None),
            LEARNING_RULE_MANAGEMENT_HINT,
        ]
    )


def format_bank_learning_rule_status_updated(result: BankLearningRuleStatusResult) -> str:
    return "\n".join(
        [
            "Режим правила обновлён:",
            "",
            f"{result.bank.upper()} · {result.merchant_display} → {result.category_title}",
            f"Режим: {_mode_label(result.mode)}",
            "",
            _mode_explanation(result.mode, hit_count=result.hit_count),
        ]
    )


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "ещё не было"
    return value.strftime("%d.%m.%Y %H:%M")


def _mode_label(mode: BankCategoryRuleMode) -> str:
    if mode == BankCategoryRuleMode.AUTOSAVE:
        return "автосохранение"
    if mode == BankCategoryRuleMode.SUGGEST:
        return "только подсказка"
    return "отключено"


def _mode_explanation(mode: BankCategoryRuleMode, *, hit_count: int | None) -> str:
    if mode == BankCategoryRuleMode.AUTOSAVE:
        if hit_count is not None and hit_count < 2:
            return "Автосохранение включено, но начнётся после ещё одного подтверждения."
        return "Похожие SMS будут записываться автоматически, если нет конфликта с парсером."
    if mode == BankCategoryRuleMode.SUGGEST:
        return "Бот будет подставлять эту категорию, но расход всё равно нужно подтвердить."
    return "Бот не будет использовать это правило для похожих SMS."
