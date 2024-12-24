import logging
from datetime import datetime
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.data_storage import save_data_to_csv, save_data_to_sheets

logging.basicConfig(level=logging.INFO)

# Стейт-машина для состояния пользователя
class ExpenseState(StatesGroup):
    expense_category = State()
    expense_amount = State()
    expense_description = State()

# Обработчик для добавления расхода
async def add_expense(message: types.Message, state: FSMContext):
    logging.info("Обработчик add_expense запущен.")
    
    # Создаем кнопки для выбора категории расхода
    salon = InlineKeyboardButton(text="Салон", callback_data="expense_салон")
    flat = InlineKeyboardButton(text="Квартира", callback_data="expense_квартира")
    taxes = InlineKeyboardButton(text="Налоги", callback_data="expense_налоги")
    storage = InlineKeyboardButton(text="Кладовка", callback_data="expense_кладовка")
    food = InlineKeyboardButton(text="Питание", callback_data="expense_питание")
    entertainment = InlineKeyboardButton(text="Развлечение", callback_data="expense_развлечение")
    
    # Создаем inline клавиатуру с кнопками
    main_kb = InlineKeyboardMarkup(inline_keyboard=[
        [salon, flat, taxes],
        [storage, food, entertainment]
    ])

    # Отправляем сообщение с клавиатурой
    await message.answer("Выберите категорию расхода:", reply_markup=main_kb)
    logging.info("Пользователю отправлено сообщение с категориями расхода.")

    # Устанавливаем состояние
    await state.set_state(ExpenseState.expense_category)
    logging.info("Состояние установлено: expense_category")

# Обработчик для выбора категории расхода
async def expense_category_selected(call: types.CallbackQuery, state: FSMContext):
    logging.info(f"Текущее состояние перед вызовом обработчика: {await state.get_state()}")
    logging.info(f"Callback data получено: {call.data}")

    category = call.data.split('_')[1]  # Извлекаем категорию из callback_data
    status = "Активный"  # Статус по умолчанию

    # Логика определения статуса в зависимости от категории
    if category in ["квартира", "налоги", "кладовка"]:
        status = "Пассивный"
    elif category == "салон":
        status = ""  # Пустой статус для категории "Салон"

    # Логирование
    logging.info(f"Выбрана категория: {category} ({status})")

    # Сохраняем категорию и статус в состояние
    await state.update_data(expense_category=category, expense_status=status)
    logging.info("Категория и статус расхода сохранены в состоянии.")

    # Попросим пользователя ввести сумму
    await call.message.answer(f"Вы выбрали категорию: {category}. Введите сумму расхода:")
    logging.info("Пользователю отправлено сообщение для ввода суммы.")
    await state.set_state(ExpenseState.expense_amount)
    logging.info("Состояние установлено: expense_amount")

# Обработчик для ввода суммы расхода
async def expense_amount_entered(message: types.Message, state: FSMContext):
    logging.info(f"Текущее состояние перед вызовом обработчика: {await state.get_state()}")
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
        await state.update_data(expense_amount=amount)
        logging.info("Сумма расхода сохранена в состоянии.")

        # Переход к описанию расхода
        await message.answer("Введите описание расхода:")
        logging.info("Пользователю отправлено сообщение для ввода описания.")
        await state.set_state(ExpenseState.expense_description)
        logging.info("Состояние установлено: expense_description")
    except ValueError as e:
        logging.error(f"Некорректная сумма: {message.text} - {e}")
        await message.answer("Пожалуйста, введите корректную сумму. Используйте только цифры и точку.")

# Обработчик для ввода описания расхода
async def expense_description_entered(message: types.Message, state: FSMContext):
    logging.info(f"Текущее состояние перед вызовом обработчика: {await state.get_state()}")
    logging.info(f"Пользователь ввел описание: {message.text}")
    description = message.text.strip()

    if not description:
        logging.warning("Пустое описание от пользователя.")
        await message.answer("Описание не может быть пустым. Пожалуйста, введите описание расхода.")
        return

    user_data = await state.get_data()
    logging.info(f"Данные из состояния: {user_data}")

    category = user_data.get("expense_category")
    amount = user_data.get("expense_amount")
    status = user_data.get("expense_status")

    date = datetime.now().strftime("%d.%m.%Y")
    entry_type = "расход"  # Устанавливаем тип как "расход"

    save_data_to_csv(date, category, amount, entry_type, description, status)
    logging.info("Данные сохранены в CSV.")
    save_data_to_sheets(date, category, amount, entry_type, description, status)
    logging.info("Данные сохранены в Google Sheets.")

    await message.answer(f"Расход {category} ({status}) на сумму {amount} был успешно добавлен.")
    logging.info("Пользователю отправлено сообщение о завершении процесса.")
    await state.clear()  # Завершаем FSM
    logging.info("Состояние сброшено.")
