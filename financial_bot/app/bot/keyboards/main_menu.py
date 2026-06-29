from aiogram.types import ReplyKeyboardMarkup

from financial_bot.app.bot.keyboards.menu_builder import build_reply_menu

MAIN_MENU_ROWS: tuple[tuple[str, ...], ...] = (
    ("➕ Расход", "➕ Доход"),
    ("🏦 Автоучёт", "📊 Отчёты"),
    ("💰 Бюджет", "⚙️ Настройки"),
)


def build_main_menu() -> ReplyKeyboardMarkup:
    return build_reply_menu(MAIN_MENU_ROWS, placeholder="Введите сумму или выберите действие")
