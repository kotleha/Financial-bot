from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from financial_bot.app.services.bank_learning_rule_service import BankLearningRuleLine
from financial_bot.app.services.transaction_service import CategoryOption


class BankLearningAction(StrEnum):
    CHANGE_CATEGORY = "cat"
    DISABLE = "off"
    ENABLE = "on"
    BACK = "back"


class BankLearningRuleCallback(CallbackData, prefix="blr"):
    rule_id: int


class BankLearningActionCallback(CallbackData, prefix="bla"):
    action: BankLearningAction
    rule_id: int


class BankLearningCategoryCallback(CallbackData, prefix="blcat"):
    rule_id: int
    category_id: int


def build_bank_learning_rules_keyboard(
    rules: tuple[BankLearningRuleLine, ...],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_format_rule_button(line),
                callback_data=BankLearningRuleCallback(rule_id=line.id).pack(),
            )
        ]
        for line in rules
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_bank_learning_rule_actions_keyboard(
    *,
    rule_id: int,
    is_active: bool,
) -> InlineKeyboardMarkup:
    toggle_action = BankLearningAction.DISABLE if is_active else BankLearningAction.ENABLE
    toggle_text = "⏸ Отключить" if is_active else "▶️ Включить"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _action_button("🏷 Сменить категорию", BankLearningAction.CHANGE_CATEGORY, rule_id),
                _action_button(toggle_text, toggle_action, rule_id),
            ],
            [_action_button("↩️ К правилам", BankLearningAction.BACK, rule_id)],
        ]
    )


def build_bank_learning_category_keyboard(
    *,
    rule_id: int,
    categories: tuple[CategoryOption, ...],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{category.sort_order}. {category.title}",
                callback_data=BankLearningCategoryCallback(
                    rule_id=rule_id,
                    category_id=category.id,
                ).pack(),
            )
        ]
        for category in categories
    ]
    rows.append([_action_button("↩️ К правилу", BankLearningAction.BACK, rule_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _action_button(
    text: str,
    action: BankLearningAction,
    rule_id: int,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=BankLearningActionCallback(action=action, rule_id=rule_id).pack(),
    )


def _format_rule_button(line: BankLearningRuleLine) -> str:
    status = "✅" if line.is_active else "⏸"
    bank = line.bank.upper()
    merchant = _shorten(line.merchant_display, max_length=28)
    category = _shorten(line.category_title, max_length=26)
    return f"{status} {bank} · {merchant} → {category}"


def _shorten(text: str, *, max_length: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_length:
        return clean
    return clean[: max_length - 1].rstrip() + "…"
