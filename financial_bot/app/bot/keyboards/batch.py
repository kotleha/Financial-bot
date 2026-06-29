from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BATCH_CANCEL_CALLBACK = "batch_cancel"


def build_batch_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Отменить добавленные операции",
                    callback_data=BATCH_CANCEL_CALLBACK,
                )
            ]
        ]
    )
