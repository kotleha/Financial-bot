from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

async def start_handler(message):
    # Создание кнопок с именованными аргументами
    button1 = KeyboardButton(text="Добавить доход")
    button2 = KeyboardButton(text="Добавить расход")
    button3 = KeyboardButton(text="Получить отчет")
    button4 = KeyboardButton(text="Экспорт данных")

    # Создание клавиатуры с типом 'reply'
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[button1], [button2], [button3], [button4]],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )

    # Отправка сообщения с клавиатурой
    await message.answer("Добро пожаловать! Выберите действие:", reply_markup=keyboard)
