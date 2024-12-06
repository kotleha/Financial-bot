import logging
import asyncio
from aiogram import Bot, Dispatcher, F  # правильный импорт
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from config import BOT_TOKEN
from handlers.start_handler import start_handler  # Импортируем саму функцию
from handlers.menu_handler import menu_handler
from handlers.income_handler import add_income, income_category_selected, income_amount_entered, income_description_entered
from aiogram.fsm.context import FSMContext

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
dp.callback_query.register(income_category_selected, F.state == "waiting_for_income_category")  # правильная регистрация для callback_query
dp.message.register(income_amount_entered, F.state == "waiting_for_income_amount")
dp.message.register(income_description_entered, F.state == "waiting_for_income_description")

async def main():
    # Запускаем polling
    await dp.start_polling(bot, storage=storage)

if __name__ == "__main__":
    asyncio.run(main())
