from aiogram.types import ReplyKeyboardMarkup

from financial_bot.app.bot.keyboards.menu_builder import build_reply_menu

REPORTS_MENU_ROWS: tuple[tuple[str, ...], ...] = (
    ("🧾 Итог месяца", "📊 Месяц"),
    ("📊 Неделя", "📊 Квартал"),
    ("📊 Полгода", "📊 Год"),
    ("📈 Категории", "👥 Кто платил"),
    ("💸 Денежный поток", "📉 Динамика месяца"),
    ("📆 Сравнить", "📈 Тренд"),
    ("↩️ Главное меню",),
)


def build_reports_menu() -> ReplyKeyboardMarkup:
    return build_reply_menu(REPORTS_MENU_ROWS, placeholder="Выберите отчёт")
