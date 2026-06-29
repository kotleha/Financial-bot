from collections.abc import Sequence

from aiogram.utils.keyboard import InlineKeyboardBuilder

from financial_bot.app.services.transaction_service import CategoryOption

CATEGORY_CALLBACK_PREFIX = "exp_cat:"
CATEGORY_CANCEL_CALLBACK = "exp_cancel"


def build_category_keyboard(categories: Sequence[CategoryOption], *, draft_token: str):
    builder = InlineKeyboardBuilder()
    for category in categories:
        builder.button(
            text=f"{category.sort_order}. {category.title}",
            callback_data=f"{CATEGORY_CALLBACK_PREFIX}{draft_token}:{category.id}",
        )
    builder.button(text="↩️ Отменить ввод", callback_data=CATEGORY_CANCEL_CALLBACK)
    builder.adjust(1)
    return builder.as_markup()


def parse_category_callback_data(callback_data: str) -> tuple[str, int] | None:
    if not callback_data.startswith(CATEGORY_CALLBACK_PREFIX):
        return None

    payload = callback_data.removeprefix(CATEGORY_CALLBACK_PREFIX)
    draft_token, separator, raw_category_id = payload.partition(":")
    if not draft_token or not separator or not raw_category_id.isdecimal():
        return None
    return draft_token, int(raw_category_id)
