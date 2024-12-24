import logging
from datetime import datetime
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.data_storage import save_data_to_csv, save_data_to_sheets

logging.basicConfig(level=logging.INFO)

# Стейт-машина для состояния пользователя
class IncomeState(StatesGroup):
    income_category = State()
    income_amount = State()
    income_description = State()

# Обработчик для добавления дохода
async def add_income(message: types.Message, state: FSMContext):
    logging.info("Обработчик add_income запущен.")
    
    # Создаем кнопки для выбора категории дохода (если используем Inline клавиатуру)
    faq = InlineKeyboardButton(text="Зарплата", callback_data="income_зарплата")
    event = InlineKeyboardButton(text="Аренда", callback_data="income_аренда")
    prof = InlineKeyboardButton(text="Продажа", callback_data="income_продажа")
    profile = InlineKeyboardButton(text="Родители", callback_data="income_родители")
    
    # Создаем inline клавиатуру с нужными кнопками
    main_kb = InlineKeyboardMarkup(inline_keyboard=[
        [faq, event, prof, profile]
    ])

    # Отправляем сообщение с inline клавиатурой
    await message.answer("Выберите категорию дохода:", reply_markup=main_kb)
    logging.info("Пользователю отправлено сообщение с категориями дохода.")

    # Используем правильный способ установки состояния
    await state.set_state(IncomeState.income_category)
    logging.info("Состояние установлено: income_category")

# Обработчик для выбора категории дохода
async def income_category_selected(call: types.CallbackQuery, state: FSMContext):
    logging.info(f"Callback data получено: {call.data}")

    category = call.data.split('_')[1]  # Извлекаем категорию из callback_data
    status = "Активный"  # По умолчанию для всех разовый

    # Определяем статус в зависимости от категории
    if category == "аренда":
        status = "Пассивный"

    # Логирование
    logging.info(f"Выбрана категория: {category} ({status})")

    # Сохраняем категорию в состояние
    await state.update_data(income_category=category, income_status=status)
    logging.info("Категория и статус сохранены в состоянии.")

    # Попросим пользователя ввести сумму
    await call.message.answer(f"Вы выбрали категорию: {category} ({status}). Введите сумму дохода:")
    logging.info("Пользователю отправлено сообщение для ввода суммы.")
    await state.set_state(IncomeState.income_amount)
    logging.info("Состояние установлено: income_amount")

# Обработчик для ввода суммы дохода
async def income_amount_entered(message: types.Message, state: FSMContext):
    logging.info(f"Пользователь ввел сумму: {message.text}")
    try:
        # Удаляем лишние символы, оставляя только цифры и точку
        clean_amount = ''.join(char for char in message.text.replace(',', '.') if char.isdigit() or char == '.')
        logging.info(f"Очищенная сумма: {clean_amount}")

        # Проверяем, что сумма валидна
        if not clean_amount or not any(char.isdigit() for char in clean_amount):
            raise ValueError("Сумма должна содержать только цифры и точку.")

        amount = float(clean_amount)  # Преобразуем в float
        logging.info(f"Сумма успешно преобразована в float: {amount}")

        # Сохраняем сумму в состояние
        await state.update_data(income_amount=amount)
        logging.info("Сумма сохранена в состоянии.")

        # Переход к описанию дохода
        await message.answer("Введите описание дохода:")
        logging.info("Пользователю отправлено сообщение для ввода описания.")
        await state.set_state(IncomeState.income_description)
        logging.info("Состояние установлено: income_description")
    except ValueError as e:
        # Если ошибка, выводим лог и сообщение
        logging.error(f"Некорректная сумма: {message.text} - {e}")
        await message.answer("Пожалуйста, введите корректную сумму. Используйте только цифры и точку.")

# Обработчик для ввода описания дохода
async def income_description_entered(message: types.Message, state: FSMContext):
    logging.info(f"Пользователь ввел описание: {message.text}")
    logging.info(f"Текущее состояние перед обработкой описания: {await state.get_state()}")
    
    description = message.text.strip()  # Удаляем лишние пробелы

    # Проверяем, что описание не пустое
    if not description:
        logging.warning("Пустое описание от пользователя.")
        await message.answer("Описание не может быть пустым. Пожалуйста, введите описание дохода.")
        return

    # Получаем данные из состояния
    user_data = await state.get_data()
    logging.info(f"Данные из состояния: {user_data}")

    category = user_data.get("income_category")
    amount = user_data.get("income_amount")
    status = user_data.get("income_status")

    # Генерируем текущую дату
    date = datetime.now().strftime("%d.%m.%Y")

    # Указываем тип записи
    entry_type = "доход"

    # Сохраняем данные в CSV и Google Sheets
    save_data_to_csv(date, category, amount, entry_type, description, status)
    logging.info("Данные сохранены в CSV.")
    save_data_to_sheets(date, category, amount, entry_type, description, status)
    logging.info("Данные сохранены в Google Sheets.")

    # Завершаем диалог
    await message.answer(f"Доход {category} ({status}) на сумму {amount} был успешно добавлен.")
    logging.info("Пользователю отправлено сообщение о завершении процесса.")
    await state.clear()  # Завершаем FSM
    logging.info("Состояние сброшено.")
