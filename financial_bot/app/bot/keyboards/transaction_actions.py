from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class TransactionAction(StrEnum):
    AMOUNT = "amount"
    CATEGORY = "category"
    DATE = "date"
    PAYER = "payer"
    COMMENT = "comment"
    DELETE = "delete"


class TransactionActionCallback(CallbackData, prefix="tx"):
    action: TransactionAction
    transaction_id: int


def build_transaction_actions_keyboard(transaction_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("💰 Изменить сумму", TransactionAction.AMOUNT, transaction_id),
                _button("🏷 Изменить категорию", TransactionAction.CATEGORY, transaction_id),
            ],
            [
                _button("📅 Изменить дату", TransactionAction.DATE, transaction_id),
                _button("👤 Изменить плательщика", TransactionAction.PAYER, transaction_id),
            ],
            [
                _button("💬 Изменить комментарий", TransactionAction.COMMENT, transaction_id),
                _button("🗑 Удалить операцию", TransactionAction.DELETE, transaction_id),
            ],
        ]
    )


def _button(
    text: str,
    action: TransactionAction,
    transaction_id: int,
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=TransactionActionCallback(
            action=action,
            transaction_id=transaction_id,
        ).pack(),
    )
