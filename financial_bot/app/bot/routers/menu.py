from aiogram import F, Router
from aiogram.types import Message

from financial_bot.app.bot.keyboards.auto_accounting_menu import build_auto_accounting_menu
from financial_bot.app.bot.keyboards.budget_menu import build_budget_menu
from financial_bot.app.bot.keyboards.main_menu import build_main_menu
from financial_bot.app.bot.keyboards.reports_menu import build_reports_menu
from financial_bot.app.bot.keyboards.settings_menu import build_settings_menu

router = Router(name=__name__)

REPORTS_MENU_ALIASES = {"📊 отчёты", "📊 отчеты", "отчёты", "отчеты"}
BUDGET_MENU_ALIASES = {"💰 бюджет"}
AUTO_ACCOUNTING_MENU_ALIASES = {
    "🏦 автоучёт",
    "🏦 автоучет",
    "автоучёт",
    "автоучет",
}
SETTINGS_MENU_ALIASES = {
    "⚙️ настройки",
    "настройки",
}
BACK_ALIASES = {
    "↩️ назад",
    "↩️ главное меню",
    "главное меню",
    "назад",
}
AUTO_ACCOUNTING_HELP_ALIASES = {
    "ℹ️ как работает автоучёт",
    "ℹ️ как работает автоучет",
    "как работает автоучёт",
    "как работает автоучет",
}
BANK_SETTINGS_HELP_ALIASES = {
    "🏦 банки",
    "банки",
}


@router.message(F.text.func(lambda text: text.strip().lower() in REPORTS_MENU_ALIASES))
async def reports_menu_selected(message: Message) -> None:
    await message.answer("Выберите отчёт.", reply_markup=build_reports_menu())


@router.message(F.text.func(lambda text: text.strip().lower() in BUDGET_MENU_ALIASES))
async def budget_menu_selected(message: Message) -> None:
    await message.answer("Выберите раздел бюджета.", reply_markup=build_budget_menu())


@router.message(F.text.func(lambda text: text.strip().lower() in AUTO_ACCOUNTING_MENU_ALIASES))
async def auto_accounting_menu_selected(message: Message) -> None:
    await message.answer("Выберите действие автоучёта.", reply_markup=build_auto_accounting_menu())


@router.message(F.text.func(lambda text: text.strip().lower() in SETTINGS_MENU_ALIASES))
async def settings_menu_selected(message: Message) -> None:
    await message.answer("Выберите настройку.", reply_markup=build_settings_menu())


@router.message(F.text.func(lambda text: text.strip().lower() in BACK_ALIASES))
async def back_to_main_menu_selected(message: Message) -> None:
    await message.answer("Главное меню.", reply_markup=build_main_menu())


@router.message(F.text.func(lambda text: text.strip().lower() in AUTO_ACCOUNTING_HELP_ALIASES))
async def auto_accounting_help_selected(message: Message) -> None:
    await message.answer(
        "Автоучёт принимает банковские SMS через iPhone Shortcuts и сохраняет событие.\n\n"
        "Новые расходы требуют подтверждения. Повторяющиеся расходы по выученным правилам "
        "могут записываться автоматически, но их можно исправить кнопками в карточке.\n\n"
        "Внутренние переводы можно отметить как перевод себе, они не считаются расходом.\n\n"
        "Поступления можно учесть отдельной кнопкой «Учесть доход». Доходы видны в отчёте "
        "«Денежный поток», но не входят в расходные лимиты и графики категорий.\n\n"
        "Возвраты можно учесть как корректировку расходов выбранной категории."
    )


@router.message(F.text.func(lambda text: text.strip().lower() in BANK_SETTINGS_HELP_ALIASES))
async def bank_settings_help_selected(message: Message) -> None:
    await message.answer(
        "Банковские источники уже работают через защищённый HTTPS endpoint и iPhone Shortcuts.\n\n"
        "Сейчас управление источниками делается на сервере. Кнопочное управление источниками "
        "лучше добавлять после завершения настройки телефонов."
    )
