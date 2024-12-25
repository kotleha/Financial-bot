import logging
import asyncio
from config import BOT_TOKEN
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter
from handlers.start_handler import start_handler
from handlers.income_handler import IncomeState, add_income, income_category_selected, income_amount_entered, income_description_entered
from handlers.expense_handler import ExpenseState, add_expense, expense_category_selected, expense_amount_entered, expense_description_entered
from handlers.report_handler import report_select_period_step1, handle_report_start_year, handle_report_start_month, handle_report_end_year, handle_report_end_month
from handlers.export_handler import export_data_step1, handle_start_year, handle_start_month, handle_end_year, handle_end_month

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем экземпляр бота
bot = Bot(token=BOT_TOKEN)

# Создаем хранилище состояний
storage = MemoryStorage()

# Создаем экземпляр диспетчера
dp = Dispatcher()

# Регистрируем обработчики с использованием фильтров
dp.message.register(start_handler, Command("start"))

# Обработчик для добавления дохода с фильтром текста
dp.message.register(add_income, F.text == "Добавить доход")
dp.callback_query.register(income_category_selected, F.data.startswith("income_"))
dp.message.register(income_amount_entered, StateFilter(IncomeState.income_amount))
dp.message.register(income_description_entered, StateFilter(IncomeState.income_description))

dp.message.register(add_expense, F.text == "Добавить расход")
dp.callback_query.register(expense_category_selected, F.data.startswith("expense_"))
dp.message.register(expense_amount_entered, StateFilter(ExpenseState.expense_amount))
dp.message.register(expense_description_entered, StateFilter(ExpenseState.expense_description))

dp.message.register(report_select_period_step1, F.text == "Получить отчет")
dp.callback_query.register(handle_report_start_year, lambda c: c.data.startswith("start_year_report_"))
dp.callback_query.register(handle_report_start_month, lambda c: c.data.startswith("start_month_report_"))
dp.callback_query.register(handle_report_end_year, lambda c: c.data.startswith("end_year_report_"))
dp.callback_query.register(handle_report_end_month, lambda c: c.data.startswith("end_month_report_"))

dp.message.register(export_data_step1, F.text == "Экспорт данных")
dp.callback_query.register(handle_start_year, lambda c: c.data.startswith("start_year_") and not c.data.startswith("start_year_report_"))
dp.callback_query.register(handle_start_month, lambda c: c.data.startswith("start_month_") and not c.data.startswith("start_month_report_"))
dp.callback_query.register(handle_end_year, lambda c: c.data.startswith("end_year_") and not c.data.startswith("end_year_report_"))
dp.callback_query.register(handle_end_month, lambda c: c.data.startswith("end_month_") and not c.data.startswith("end_month_report_"))

async def main():
    await dp.start_polling(bot, storage=storage)

if __name__ == "__main__":
    asyncio.run(main())
