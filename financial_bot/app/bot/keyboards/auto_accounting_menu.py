from aiogram.types import ReplyKeyboardMarkup

from financial_bot.app.bot.keyboards.menu_builder import build_reply_menu

AUTO_ACCOUNTING_MENU_ROWS: tuple[tuple[str, ...], ...] = (
    ("🩺 Состояние автоучёта",),
    ("🔎 Проверить источники",),
    ("🔁 Повторить отправку ожидающих",),
    ("🧠 Правила категорий",),
    ("ℹ️ Как работает автоучёт",),
    ("↩️ Главное меню",),
)


def build_auto_accounting_menu() -> ReplyKeyboardMarkup:
    return build_reply_menu(
        AUTO_ACCOUNTING_MENU_ROWS,
        placeholder="Выберите действие автоучёта",
    )
