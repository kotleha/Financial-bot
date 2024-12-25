import os
import logging
from datetime import datetime
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.input_file import FSInputFile  # Для отправки файлов

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Папка для хранения CSV-файлов
CSV_FOLDER = "csv_reports"

# Глобальные переменные для временного хранения выбора периода
USER_PERIOD_SELECTION = {}  # Пример: {user_id: {"start_year": "2024", "start_month": "12"}}


def analyze_available_data():
    """
    Анализирует доступные файлы в папке CSV и возвращает список годов и месяцев.
    """
    years = {}
    if not os.path.exists(CSV_FOLDER):
        return years  # Если папка отсутствует, возвращаем пустой словарь

    for file_name in os.listdir(CSV_FOLDER):
        if file_name.endswith(".csv"):
            parts = file_name.split("_")  # Формат: NN_MonthName_YYYY.csv
            if len(parts) == 3 and parts[2].endswith(".csv"):
                year = parts[2].replace(".csv", "")
                month_number = parts[0]
                month_name = parts[1]

                if year not in years:
                    years[year] = []
                years[year].append((int(month_number), month_name))  # Сохраняем номер и название месяца

    # Сортируем месяцы в каждом году
    for year in years:
        years[year] = sorted(years[year], key=lambda x: x[0])

    return years


def generate_year_buttons(years, callback_prefix="start_year"):
    """
    Генерирует кнопки для выбора года.
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for year in sorted(years.keys()):
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=year,
                callback_data=f"{callback_prefix}_{year}"
            )
        ])
    return keyboard


def generate_month_buttons(year, months, callback_prefix="start_month"):
    """
    Генерирует кнопки для выбора месяца.
    """
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for month_number, month_name in months:
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{month_name} ({month_number})",
                callback_data=f"{callback_prefix}_{year}_{month_number}"
            )
        ])
    return keyboard


async def export_data_step1(message: types.Message):
    """
    Первый шаг: запрос начального года или месяца.
    """
    years = analyze_available_data()
    if not years:
        await message.answer("Нет доступных данных для экспорта.")
        return

    user_id = message.from_user.id  # Получаем ID пользователя

    if len(years) == 1:
        # Если доступен только один год, сразу показываем месяцы
        year = list(years.keys())[0]

        # Автоматически сохраняем год в USER_PERIOD_SELECTION
        if user_id not in USER_PERIOD_SELECTION:
            USER_PERIOD_SELECTION[user_id] = {}

        USER_PERIOD_SELECTION[user_id]["start_year"] = year

        months = years[year]
        await message.answer(
            f"Данные за {year}. Выберите начальный месяц:",
            reply_markup=generate_month_buttons(year, months, callback_prefix="start_month")
        )
    else:
        # Если доступно несколько лет, показываем годы
        await message.answer(
            "Выберите начальный год для экспорта данных:",
            reply_markup=generate_year_buttons(years, callback_prefix="start_year")
        )


async def handle_start_year(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор начального года и предлагает выбрать месяц.
    """
    user_id = callback_query.from_user.id
    year = callback_query.data.split("_")[2]

    years = analyze_available_data()
    if year in years:
        # Убедимся, что для пользователя есть запись в USER_PERIOD_SELECTION
        if user_id not in USER_PERIOD_SELECTION:
            USER_PERIOD_SELECTION[user_id] = {}

        USER_PERIOD_SELECTION[user_id]["start_year"] = year  # Сохраняем начальный год
        months = years[year]
        await callback_query.message.answer(
            f"Вы выбрали {year}. Теперь выберите начальный месяц:",
            reply_markup=generate_month_buttons(year, months, callback_prefix="start_month")
        )
    else:
        await callback_query.message.answer("Данные за выбранный год отсутствуют.")


async def handle_start_month(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор начального месяца и предлагает выбрать конечный год.
    """
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    year = data[2]
    month = data[3]

    # Убедимся, что для пользователя есть запись в USER_PERIOD_SELECTION
    if user_id not in USER_PERIOD_SELECTION:
        USER_PERIOD_SELECTION[user_id] = {}

    # Сохраняем начальный месяц и год
    USER_PERIOD_SELECTION[user_id]["start_month"] = month
    USER_PERIOD_SELECTION[user_id]["start_year"] = year

    years = analyze_available_data()
    if len(years) == 1:
        # Если доступен только один год, сразу показываем месяцы
        months = years[year]
        await callback_query.message.answer(
            f"Вы выбрали начальный период: {month}/{year}. Теперь выберите конечный месяц:",
            reply_markup=generate_month_buttons(year, months, callback_prefix="end_month")
        )
    else:
        # Если доступно несколько лет, предлагаем выбрать год
        await callback_query.message.answer(
            f"Вы выбрали начальный период: {month}/{year}. Теперь выберите конечный год:",
            reply_markup=generate_year_buttons(years, callback_prefix="end_year")
        )


async def handle_end_year(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор конечного года и предлагает выбрать конечный месяц.
    """
    user_id = callback_query.from_user.id
    year = callback_query.data.split("_")[2]

    years = analyze_available_data()
    if year in years:
        # Убедимся, что для пользователя есть запись в USER_PERIOD_SELECTION
        if user_id not in USER_PERIOD_SELECTION:
            USER_PERIOD_SELECTION[user_id] = {}

        USER_PERIOD_SELECTION[user_id]["end_year"] = year  # Сохраняем конечный год
        months = years[year]
        await callback_query.message.answer(
            f"Вы выбрали конечный год: {year}. Теперь выберите конечный месяц:",
            reply_markup=generate_month_buttons(year, months, callback_prefix="end_month")
        )
    else:
        await callback_query.message.answer("Данные за выбранный год отсутствуют.")


async def handle_end_month(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор конечного месяца и завершает процесс выбора периода.
    """
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    year = data[2]
    month = data[3]

    # Убедимся, что для пользователя есть запись в USER_PERIOD_SELECTION
    if user_id not in USER_PERIOD_SELECTION:
        USER_PERIOD_SELECTION[user_id] = {}

    # Сохраняем конечный месяц и год
    USER_PERIOD_SELECTION[user_id]["end_month"] = month
    USER_PERIOD_SELECTION[user_id]["end_year"] = year

    # Завершаем выбор периода
    start_year = USER_PERIOD_SELECTION[user_id]["start_year"]
    start_month = USER_PERIOD_SELECTION[user_id]["start_month"]
    end_year = USER_PERIOD_SELECTION[user_id]["end_year"]
    end_month = USER_PERIOD_SELECTION[user_id]["end_month"]

    await callback_query.message.answer(
        f"Вы выбрали период с {start_month}/{start_year} по {end_month}/{end_year}. Генерируем данные..."
    )

    # Отправляем файлы за выбранный период
    await send_files_for_period(callback_query.message, user_id)


async def send_files_for_period(message: types.Message, user_id):
    """
    Отправляет файлы за выбранный пользователем период.
    """
    period = USER_PERIOD_SELECTION.get(user_id, {})
    if not period:
        await message.answer("Ошибка: период не выбран.")
        return

    start_year = period.get("start_year")
    start_month = period.get("start_month")
    end_year = period.get("end_year")
    end_month = period.get("end_month")

    # Логика фильтрации файлов за выбранный период
    files_to_send = []
    for file_name in os.listdir(CSV_FOLDER):
        if file_name.endswith(".csv"):
            year = file_name.split("_")[2].replace(".csv", "")
            month = file_name.split("_")[0]
            if start_year <= year <= end_year:
                if start_year == year and month < start_month:
                    continue
                if end_year == year and month > end_month:
                    continue
                files_to_send.append(os.path.join(CSV_FOLDER, file_name))

    if not files_to_send:
        await message.answer("Нет файлов за выбранный период.")
        return

    # Отправляем файлы
    for file_path in files_to_send:
        try:
            document = FSInputFile(file_path, filename=os.path.basename(file_path))
            await message.answer_document(document)
        except Exception as e:
            logging.error(f"Ошибка при отправке файла {file_path}: {e}")
            await message.answer(f"Не удалось отправить файл {os.path.basename(file_path)}.")


# Если выбор конечного года пропускается
async def skip_end_year_step(user_id, callback_query):
    """
    Обрабатывает случай, когда выбор конечного года пропускается (только один год доступен).
    """
    years = analyze_available_data()
    if len(years) == 1:
        year = list(years.keys())[0]

        # Убедимся, что для пользователя есть запись в USER_PERIOD_SELECTION
        if user_id not in USER_PERIOD_SELECTION:
            USER_PERIOD_SELECTION[user_id] = {}

        USER_PERIOD_SELECTION[user_id]["end_year"] = year  # Сохраняем конечный год
        months = years[year]
        await callback_query.message.answer(
            f"Конечный год {year} выбран автоматически. Выберите конечный месяц:",
            reply_markup=generate_month_buttons(year, months, callback_prefix="end_month")
        )