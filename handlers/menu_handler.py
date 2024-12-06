from aiogram import types

async def menu_handler(message: types.Message):
    if message.text == "Добавить доход":
        # Логика добавления дохода
        await message.answer("Введите сумму дохода:")
    elif message.text == "Добавить расход":
        # Логика добавления расхода
        await message.answer("Введите сумму расхода:")
    elif message.text == "Получить отчет":
        # Логика генерации отчета
        await message.answer("Какой отчет вы хотите получить?", reply_markup=types.ReplyKeyboardRemove())
    elif message.text == "Экспорт данных":
        # Логика экспорта данных в CSV
        await message.answer("Данные будут экспортированы в CSV.")
