from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Стейт-машина для состояния пользователя
class UserState(StatesGroup):
    waiting_for_income_category = State()
    waiting_for_income_amount = State()
    waiting_for_income_description = State()

# Обработчик для добавления дохода
async def add_income(message: types.Message, state: FSMContext):
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

    # Используем правильный способ установки состояния
    await state.set_state(UserState.waiting_for_income_category)

# Обработчик для выбора категории дохода
async def income_category_selected(call: types.CallbackQuery, state: FSMContext):
    category = call.data.split('_')[1]  # Извлекаем категорию из callback_data
    status = "Разовый"  # По умолчанию для всех разовый

    # Определяем статус в зависимости от категории
    if category == "аренда":
        status = "Пассивный"

    # Сохраняем категорию в состояние
    await state.update_data(income_category=category, income_status=status)
    
    # Попросим пользователя ввести сумму
    await call.message.answer(f"Вы выбрали категорию: {category} ({status}). Введите сумму дохода:")
    await state.set_state(UserState.waiting_for_income_amount)

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
