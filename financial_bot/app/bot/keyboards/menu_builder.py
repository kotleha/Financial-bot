from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

type MenuRows = tuple[tuple[str, ...], ...]


def build_reply_menu(rows: MenuRows, *, placeholder: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=button_text) for button_text in row] for row in rows],
        resize_keyboard=True,
        input_field_placeholder=placeholder,
    )
