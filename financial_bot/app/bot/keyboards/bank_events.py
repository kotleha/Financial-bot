from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from financial_bot.app.services.transaction_service import CategoryOption


class BankEventAction(StrEnum):
    CONFIRM = "confirm"
    INCOME_CONFIRM = "income"
    REFUND_CORRECTION = "refund"
    CHANGE_CATEGORY = "category"
    IGNORE = "ignore"
    INTERNAL_TRANSFER = "internal"
    DISABLE_RULE = "disable_rule"
    SCOPE_HOUSEHOLD = "scope_household"
    SCOPE_SALON = "scope_salon"


class BankEventActionCallback(CallbackData, prefix="bank"):
    action: BankEventAction
    event_id: int


class BankEventCategoryCallback(CallbackData, prefix="bankcat"):
    event_id: int
    category_id: int


def build_bank_event_actions_keyboard(
    event_id: int,
    *,
    can_confirm: bool = True,
) -> InlineKeyboardMarkup:
    first_row = []
    if can_confirm:
        first_row.append(_action_button("✅ Подтвердить", BankEventAction.CONFIRM, event_id))
    first_row.append(
        _action_button("🏷 Изменить категорию", BankEventAction.CHANGE_CATEGORY, event_id)
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            first_row,
            [
                _action_button("🏠 Дом", BankEventAction.SCOPE_HOUSEHOLD, event_id),
                _action_button("💼 Салон", BankEventAction.SCOPE_SALON, event_id),
            ],
            [
                _action_button("🚫 Не учитывать", BankEventAction.IGNORE, event_id),
                _action_button("🔁 Это перевод себе", BankEventAction.INTERNAL_TRANSFER, event_id),
            ],
        ]
    )


def build_bank_autosaved_actions_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _action_button(
                    "🏷 Исправить категорию",
                    BankEventAction.CHANGE_CATEGORY,
                    event_id,
                )
            ],
            [
                _action_button("🔁 Это перевод себе", BankEventAction.INTERNAL_TRANSFER, event_id),
                _action_button("🗑 Удалить автозапись", BankEventAction.IGNORE, event_id),
            ],
            [
                _action_button("🏠 Дом", BankEventAction.SCOPE_HOUSEHOLD, event_id),
                _action_button("💼 Салон", BankEventAction.SCOPE_SALON, event_id),
            ],
            [_action_button("🚫 Отключить правило", BankEventAction.DISABLE_RULE, event_id)],
        ]
    )


def build_bank_refund_actions_keyboard(
    event_id: int,
    *,
    can_confirm: bool = True,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_confirm:
        rows.append(
            [_action_button("↩️ Учесть возврат", BankEventAction.REFUND_CORRECTION, event_id)]
        )
    rows.append([_action_button("🏷 Выбрать категорию", BankEventAction.CHANGE_CATEGORY, event_id)])
    rows.append(
        [
            _action_button("🏠 Дом", BankEventAction.SCOPE_HOUSEHOLD, event_id),
            _action_button("💼 Салон", BankEventAction.SCOPE_SALON, event_id),
        ]
    )
    rows.append([_action_button("🚫 Не корректировать", BankEventAction.IGNORE, event_id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_bank_income_actions_keyboard(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_action_button("✅ Учесть доход", BankEventAction.INCOME_CONFIRM, event_id)],
            [
                _action_button("🏠 Дом", BankEventAction.SCOPE_HOUSEHOLD, event_id),
                _action_button("💼 Салон", BankEventAction.SCOPE_SALON, event_id),
            ],
            [
                _action_button("🚫 Не учитывать", BankEventAction.IGNORE, event_id),
                _action_button("🔁 Это перевод себе", BankEventAction.INTERNAL_TRANSFER, event_id),
            ],
        ]
    )


def build_bank_event_category_keyboard(
    *,
    event_id: int,
    categories: list[CategoryOption],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{category.sort_order}. {category.title}",
                callback_data=BankEventCategoryCallback(
                    event_id=event_id,
                    category_id=category.id,
                ).pack(),
            )
        ]
        for category in categories
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _action_button(
    text: str,
    action: BankEventAction,
    event_id: int,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=BankEventActionCallback(action=action, event_id=event_id).pack(),
    )
