import logging
import asyncio
from aiogram import Bot, Dispatcher, F  # правильный импорт
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command
from config import BOT_TOKEN
from handlers.start_handler import start_handler
from handlers.menu_handler import menu_handler
from handlers.income_handler import income_handler  # Убедись, что этот импорт правильный

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Создаем экземпляр бота
bot = Bot(token=BOT_TOKEN)

# Создаем хранилище состояний
storage = MemoryStorage()

# Создаем экземпляр диспетчера
dp = Dispatcher()

# Регистрируем обработчики с использованием фильтров
dp.message.register(start_handler.start_handler, Command("start"))
dp.message.register(income_handler.add_income, F.text == "Добавить доход", state="*")  # Используем F.text
dp.message.register(income_handler.income_category_selected, state=user_data.UserState.waiting_for_income_category)
dp.message.register(income_handler.income_amount_entered, state=user_data.UserState.waiting_for_income_amount)
dp.message.register(income_handler.income_description_entered, state=user_data.UserState.waiting_for_income_description)

async def main():
    # Запускаем polling
    await dp.start_polling(bot, storage=storage)

if __name__ == "__main__":
    asyncio.run(main())
