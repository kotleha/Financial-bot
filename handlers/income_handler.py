from aiogram import types, F
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from aiogram.fsm.context import FSMContext  # Новый импорт
from services.data_storage import save_income_to_csv, save_income_to_sheets
from services import user_data
from aiogram.fsm.state import State, StatesGroup

# Стейт-машина для состояния пользователя
class UserState(StatesGroup):
    waiting_for_income_category = State()
    waiting_for_income_amount = State()
    waiting_for_income_description = State()

async def add_income(message: types.Message):
    # Создаем кнопки для выбора категории дохода
    buttons = [
        KeyboardButton("Зарплата"),
        KeyboardButton("Аренда"),
        KeyboardButton("Продажа"),
        KeyboardButton("Родители")
    ]
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True).add(*buttons)
    
    await message.answer("Выберите категорию дохода:", reply_markup=keyboard)
    await UserState.waiting_for_income_category.set()

# Обработчик для выбора категории дохода
async def income_category_selected(message: types.Message, state: FSMContext):
    category = message.text
    status = "Разовый"  # По умолчанию для всех разовый

    # Определяем статус в зависимости от категории
    if category == "Аренда":
        status = "Пассивный"

    # Сохраняем категорию в состояние
    await state.update_data(income_category=category, income_status=status)
    
    # Попросим пользователя ввести сумму
    await message.answer(f"Вы выбрали категорию: {category} ({status}). Введите сумму дохода:")
    await UserState.waiting_for_income_amount.set()

# Обработчик для ввода суммы дохода
async def income_amount_entered(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)  # Преобразуем сумму в число
        # Попросим ввести описание
        await state.update_data(income_amount=amount)
        await message.answer("Введите описание дохода:")
        await UserState.waiting_for_income_description.set()

    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму.")

# Обработчик для ввода описания дохода
async def income_description_entered(message: types.Message, state: FSMContext):
    description = message.text
    user_data = await state.get_data()

    category = user_data.get("income_category")
    amount = user_data.get("income_amount")
    status = user_data.get("income_status")

    # Сохраняем данные в CSV и Google Sheets
    save_income_to_csv(amount, category, status, description)
    save_income_to_sheets(amount, category, status, description)

    # Завершаем диалог
    await message.answer(f"Доход {category} ({status}) на сумму {amount} был успешно добавлен.")
    await state.finish()
