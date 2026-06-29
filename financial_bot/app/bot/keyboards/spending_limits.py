from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from financial_bot.app.bot.formatters.spending_limits import format_limit_rule_label
from financial_bot.app.services.spending_limit_service import LimitOverviewLine


class LimitWizardAction(StrEnum):
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    NO_LIMIT = "none"
    SAVINGS_TARGET = "target"
    BACK = "back"


class LimitWizardConfirmAction(StrEnum):
    APPLY = "apply"
    CANCEL = "cancel"


class LimitCategoryCallback(CallbackData, prefix="limcat"):
    category_code: str


class LimitActionCallback(CallbackData, prefix="limact"):
    action: LimitWizardAction
    category_code: str


class LimitConfirmCallback(CallbackData, prefix="limok"):
    action: LimitWizardConfirmAction


def build_limit_category_keyboard(
    lines: tuple[LimitOverviewLine, ...],
    *,
    currency: str,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=(
                    f"{line.sort_order}. {line.title} — "
                    f"{format_limit_rule_label(line.kind, line.amount, currency)}"
                ),
                callback_data=LimitCategoryCallback(category_code=line.code).pack(),
            )
        ]
        for line in lines
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_limit_action_keyboard(
    *,
    category_code: str,
    allow_seasonal: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            _action_button("💰 Лимит в месяц", LimitWizardAction.MONTHLY, category_code),
            _action_button("🚫 Без лимита", LimitWizardAction.NO_LIMIT, category_code),
        ],
        [
            _action_button("🏦 Цель накопления", LimitWizardAction.SAVINGS_TARGET, category_code),
        ],
    ]
    if allow_seasonal:
        rows.append(
            [
                _action_button(
                    "☀️❄️ Лето/зима",
                    LimitWizardAction.SEASONAL,
                    category_code,
                )
            ]
        )
    rows.append([_action_button("↩️ К категориям", LimitWizardAction.BACK, category_code)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_limit_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=LimitConfirmCallback(
                        action=LimitWizardConfirmAction.APPLY
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="↩️ Отмена",
                    callback_data=LimitConfirmCallback(
                        action=LimitWizardConfirmAction.CANCEL
                    ).pack(),
                ),
            ]
        ]
    )


def _action_button(
    text: str,
    action: LimitWizardAction,
    category_code: str,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=LimitActionCallback(action=action, category_code=category_code).pack(),
    )
