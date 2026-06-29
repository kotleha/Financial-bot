from aiogram.types import ReplyKeyboardMarkup

from financial_bot.app.bot.keyboards.menu_builder import build_reply_menu

SETTINGS_MENU_ROWS: tuple[tuple[str, ...], ...] = (
    ("🏷 Категории", "🔤 Алиасы"),
    ("🧾 Лимиты", "⏰ Напоминания"),
    ("🏦 Банки",),
    ("↩️ Главное меню",),
)


def build_settings_menu() -> ReplyKeyboardMarkup:
    return build_reply_menu(SETTINGS_MENU_ROWS, placeholder="Выберите настройку")
