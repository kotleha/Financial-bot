from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class MonthCloseAction(StrEnum):
    DASHBOARD = "dashboard"
    BANK_PENDING = "bank_pending"
    SUMMARY = "summary"


class MonthCloseActionCallback(CallbackData, prefix="mclose"):
    action: MonthCloseAction


def build_month_close_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("📊 Дашборд месяца", MonthCloseAction.DASHBOARD)],
            [_button("🏦 Операции банка", MonthCloseAction.BANK_PENDING)],
            [_button("🧾 Итог месяца", MonthCloseAction.SUMMARY)],
        ]
    )


def _button(text: str, action: MonthCloseAction) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=MonthCloseActionCallback(action=action).pack(),
    )
