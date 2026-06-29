from aiogram.types import ReplyKeyboardMarkup

from financial_bot.app.bot.keyboards.menu_builder import build_reply_menu

BUDGET_MENU_ROWS: tuple[tuple[str, ...], ...] = (
    ("📋 Сводка бюджета",),
    ("🧾 Лимиты", "🏦 Копилка"),
    ("⚙️ Настроить лимиты",),
    ("↩️ Главное меню",),
)


def build_budget_menu() -> ReplyKeyboardMarkup:
    return build_reply_menu(BUDGET_MENU_ROWS, placeholder="Выберите раздел бюджета")
