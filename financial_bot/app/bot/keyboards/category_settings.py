from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from financial_bot.app.services.category_settings_service import CategorySettingsLine


class CategorySettingsAction(StrEnum):
    RENAME = "rename"
    ADD_ALIAS = "alias"
    BACK = "back"


class CategorySettingsConfirmAction(StrEnum):
    APPLY = "apply"
    CANCEL = "cancel"


class CategorySettingsCategoryCallback(CallbackData, prefix="catset"):
    category_code: str


class CategorySettingsActionCallback(CallbackData, prefix="catact"):
    action: CategorySettingsAction
    category_code: str


class CategorySettingsConfirmCallback(CallbackData, prefix="catok"):
    action: CategorySettingsConfirmAction


def build_category_settings_keyboard(
    lines: tuple[CategorySettingsLine, ...],
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{line.sort_order}. {line.title} · {line.alias_count} алиасов",
                callback_data=CategorySettingsCategoryCallback(category_code=line.code).pack(),
            )
        ]
        for line in lines
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_category_settings_action_keyboard(category_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _action_button("✏️ Переименовать", CategorySettingsAction.RENAME, category_code),
                _action_button("➕ Алиас", CategorySettingsAction.ADD_ALIAS, category_code),
            ],
            [_action_button("↩️ К категориям", CategorySettingsAction.BACK, category_code)],
        ]
    )


def build_category_settings_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=CategorySettingsConfirmCallback(
                        action=CategorySettingsConfirmAction.APPLY
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="↩️ Отмена",
                    callback_data=CategorySettingsConfirmCallback(
                        action=CategorySettingsConfirmAction.CANCEL
                    ).pack(),
                ),
            ]
        ]
    )


def _action_button(
    text: str,
    action: CategorySettingsAction,
    category_code: str,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=CategorySettingsActionCallback(
            action=action,
            category_code=category_code,
        ).pack(),
    )
