import os
import pandas as pd
import matplotlib.pyplot as plt
import io
import logging
import uuid
import tempfile  # Imported tempfile
from datetime import datetime
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram import Dispatcher

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Папка для CSV-файлов
CSV_FOLDER = "csv_reports"

# Глобальные переменные для временного хранения выбора периода
USER_REPORT_PERIOD = {}  # Пример: {user_id: {"start_year": "2024", "start_month": "12"}}


def save_plot_to_tempfile(fig, filename_prefix):
    """
    Saves a matplotlib figure to a temporary file and returns the file path.
    """
    # Create a temporary directory if it doesn't exist
    temp_dir = tempfile.gettempdir()
    
    # Generate a unique filename using UUID to ensure uniqueness
    unique_id = uuid.uuid4().hex
    filename = f"{filename_prefix}_{unique_id}.png"
    file_path = os.path.join(temp_dir, filename)
    
    # Save the figure to the temporary file
    fig.savefig(file_path, format="png", bbox_inches='tight')
    plt.close(fig)  # Close the figure to free memory
    
    return file_path


def analyze_report_available_data():
    """
    Анализирует доступные файлы в папке CSV и возвращает список годов и месяцев.
    """
    years = {}
    if not os.path.exists(CSV_FOLDER):
        logger.warning(f"Папка '{CSV_FOLDER}' не существует.")
        return years  # Если папка отсутствует, возвращаем пустой словарь

    for file_name in os.listdir(CSV_FOLDER):
        if file_name.endswith(".csv"):
            parts = file_name.split("_")  # Формат: NN_MonthName_YYYY.csv
            if len(parts) == 3 and parts[2].replace(".csv", "").isdigit():
                year = parts[2].replace(".csv", "").strip()
                month_number = parts[0].strip()
                month_name = parts[1].strip()

                if year not in years:
                    years[year] = []
                years[year].append((int(month_number), month_name))  # Сохраняем номер и название месяца

    # Сортируем месяцы в каждом году
    for year in years:
        years[year] = sorted(years[year], key=lambda x: x[0])

    logger.info(f"Анализ доступных данных: {years}")
    return years


def generate_report_year_buttons(years, callback_prefix="start_year_report"):
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


def generate_report_month_buttons(year, months, callback_prefix="start_month_report"):
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


async def report_select_period_step1(message: types.Message):
    """
    Первый шаг: выбор начального года или месяца.
    """
    years = analyze_report_available_data()
    if not years:
        await message.answer("Нет доступных данных для анализа.")
        return

    user_id = message.from_user.id  # Получаем ID пользователя

    if len(years) == 1:
        # Если доступен только один год, сразу показываем месяцы
        year = list(years.keys())[0]

        # Автоматически сохраняем год в USER_REPORT_PERIOD
        if user_id not in USER_REPORT_PERIOD:
            USER_REPORT_PERIOD[user_id] = {}

        USER_REPORT_PERIOD[user_id]["start_year"] = year

        months = years[year]
        await message.answer(
            f"Данные за {year}. Выберите начальный месяц:",
            reply_markup=generate_report_month_buttons(year, months, callback_prefix="start_month_report")
        )
    else:
        # Если доступно несколько лет, показываем годы
        await message.answer(
            "Выберите начальный год для анализа данных:",
            reply_markup=generate_report_year_buttons(years, callback_prefix="start_year_report")
        )


async def handle_report_start_year(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор начального года для отчёта.
    """
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    
    logger.info(f"handle_report_start_year called with data: {data}")

    if len(data) < 4 or not data[3].isdigit():
        await callback_query.message.answer("Ошибка обработки данных. Попробуйте ещё раз.")
        return

    year = data[3]  # Получаем год

    years = analyze_report_available_data()
    if year in years:
        if user_id not in USER_REPORT_PERIOD:
            USER_REPORT_PERIOD[user_id] = {}

        USER_REPORT_PERIOD[user_id]["start_year"] = year  # Сохраняем начальный год
        months = years[year]
        await callback_query.message.answer(
            f"Вы выбрали {year}. Теперь выберите начальный месяц:",
            reply_markup=generate_report_month_buttons(year, months, callback_prefix="start_month_report")
        )
    else:
        await callback_query.message.answer("Данные за выбранный год отсутствуют.")


async def handle_report_start_month(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор начального месяца и предлагает выбрать конечный год.
    """
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    
    logger.info(f"handle_report_start_month called with data: {data}")

    if len(data) < 5 or not data[3].isdigit() or not data[4].isdigit():
        await callback_query.message.answer("Ошибка обработки данных. Попробуйте ещё раз.")
        return

    year = data[3]
    month = data[4]

    # Убедимся, что для пользователя есть запись в USER_REPORT_PERIOD
    if user_id not in USER_REPORT_PERIOD:
        USER_REPORT_PERIOD[user_id] = {}

    # Сохраняем начальный месяц и год
    USER_REPORT_PERIOD[user_id]["start_month"] = month
    USER_REPORT_PERIOD[user_id]["start_year"] = year

    # Проверяем, существует ли год в анализируемых данных
    years = analyze_report_available_data()
    if year not in years:
        await callback_query.message.answer("Данные за выбранный год отсутствуют.")
        return

    if len(years) == 1:
        # Если доступен только один год, сразу показываем месяцы для конечного периода
        months = years[year]
        await callback_query.message.answer(
            f"Вы выбрали начальный период: {month}/{year}. Теперь выберите конечный месяц:",
            reply_markup=generate_report_month_buttons(year, months, callback_prefix="end_month_report")
        )
    else:
        # Если доступно несколько лет, предлагаем выбрать конечный год
        await callback_query.message.answer(
            f"Вы выбрали начальный период: {month}/{year}. Теперь выберите конечный год:",
            reply_markup=generate_report_year_buttons(years, callback_prefix="end_year_report")
        )


async def handle_report_end_year(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор конечного года и предлагает выбрать конечный месяц.
    """
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    
    logger.info(f"handle_report_end_year called with data: {data}")

    if len(data) < 4 or not data[3].isdigit():
        await callback_query.message.answer("Ошибка обработки данных. Попробуйте ещё раз.")
        return

    year = data[3]  # Получаем год

    years = analyze_report_available_data()
    if year in years:
        # Убедимся, что для пользователя есть запись в USER_REPORT_PERIOD
        if user_id not in USER_REPORT_PERIOD:
            USER_REPORT_PERIOD[user_id] = {}

        USER_REPORT_PERIOD[user_id]["end_year"] = year  # Сохраняем конечный год
        months = years[year]
        await callback_query.message.answer(
            f"Вы выбрали конечный год: {year}. Теперь выберите конечный месяц:",
            reply_markup=generate_report_month_buttons(year, months, callback_prefix="end_month_report")
        )
    else:
        await callback_query.message.answer("Данные за выбранный год отсутствуют.")


async def handle_report_end_month(callback_query: types.CallbackQuery):
    """
    Обрабатывает выбор конечного месяца и завершает процесс выбора периода.
    """
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    
    logger.info(f"handle_report_end_month called with data: {data}")

    # Исправляем условие проверки
    if len(data) < 5 or not data[3].isdigit() or not data[4].isdigit():
        await callback_query.message.answer("Ошибка обработки данных. Попробуйте ещё раз.")
        return

    year = data[3]
    month = data[4]

    # Убедимся, что для пользователя есть запись в USER_REPORT_PERIOD
    if user_id not in USER_REPORT_PERIOD:
        USER_REPORT_PERIOD[user_id] = {}

    # Сохраняем конечный месяц и год
    USER_REPORT_PERIOD[user_id]["end_month"] = month
    USER_REPORT_PERIOD[user_id]["end_year"] = year

    # Завершаем выбор периода
    start_year = USER_REPORT_PERIOD[user_id].get("start_year")
    start_month = USER_REPORT_PERIOD[user_id].get("start_month")
    end_year = USER_REPORT_PERIOD[user_id].get("end_year")
    end_month = USER_REPORT_PERIOD[user_id].get("end_month")

    if not all([start_year, start_month, end_year, end_month]):
        await callback_query.message.answer("Не все параметры периода выбраны. Попробуйте ещё раз.")
        return

    await callback_query.message.answer(
        f"Вы выбрали период с {start_month}/{start_year} по {end_month}/{end_year}. Генерация отчета..."
    )

    # Здесь вызываем функцию для загрузки данных и создания отчета
    await generate_report(callback_query.message, start_year, start_month, end_year, end_month)


def load_report_data():
    """
    Загрузка и предварительная обработка данных из CSV.
    """
    all_files = [os.path.join(CSV_FOLDER, f) for f in os.listdir(CSV_FOLDER) if f.endswith(".csv")]
    if not all_files:
        logging.warning("Папка CSV пустая или не существует.")
        return pd.DataFrame()

    data_frames = []
    for file in all_files:
        try:
            df = pd.read_csv(file, delimiter=",")  # Изменён разделитель на запятую
            logging.info(f"Файл '{file}' загружен. Столбцы: {df.columns.tolist()}")
            data_frames.append(df)
        except Exception as e:
            logging.error(f"Ошибка при загрузке файла '{file}': {e}")

    if not data_frames:
        logging.warning("Нет загруженных данных после чтения всех файлов.")
        return pd.DataFrame()

    data = pd.concat(data_frames, ignore_index=True)
    logging.info(f"Объединённые данные. Столбцы: {data.columns.tolist()}")

    # Преобразование столбца 'Дата'
    try:
        data["Дата"] = pd.to_datetime(data["Дата"], format="%d.%m.%Y")
    except KeyError:
        logging.error("Столбец 'Дата' отсутствует в данных.")
        raise
    except Exception as e:
        logging.error(f"Ошибка при преобразовании столбца 'Дата': {e}")
        raise

    # Преобразование столбца 'Сумма'
    try:
        data["Сумма"] = data["Сумма"].str.replace("р.", "", regex=False) \
                                   .str.replace("\xa0", "", regex=False) \
                                   .str.replace(",", ".", regex=False) \
                                   .astype(float)
    except KeyError:
        logging.error("Столбец 'Сумма' отсутствует в данных.")
        raise
    except Exception as e:
        logging.error(f"Ошибка при преобразовании столбца 'Сумма': {e}")
        raise

    return data


async def generate_report(message: types.Message, start_year, start_month, end_year, end_month):
    """
    Генерация отчетов за выбранный период с визуализациями.
    """
    data = load_report_data()
    if data.empty:
        await message.answer("❌ **Нет данных для генерации отчета.**")
        return

    # Фильтруем данные по периоду
    try:
        data = data[
            (data["Дата"].dt.year >= int(start_year)) &
            (data["Дата"].dt.year <= int(end_year)) &
            (data["Дата"].dt.month >= int(start_month)) &
            (data["Дата"].dt.month <= int(end_month))
        ]
    except KeyError as e:
        logging.error(f"Отсутствует столбец при фильтрации данных: {e}")
        await message.answer("❌ **Ошибка в данных. Некорректные столбцы.**")
        return
    except Exception as e:
        logging.error(f"Ошибка при фильтрации данных: {e}")
        await message.answer("❌ **Ошибка обработки данных. Попробуйте позже.**")
        return

    if data.empty:
        await message.answer("ℹ️ **Нет данных за выбранный период.**")
        return

    # Сводный отчет с визуализацией
    try:
        total_income = data[data["Тип"] == "доход"]["Сумма"].sum()
        total_expense = data[data["Тип"] == "расход"]["Сумма"].sum()
        balance = total_income - total_expense

        # Формирование текстового отчета
        summary_report = (
            f"📊 <b>Сводный отчет за период:</b>\n"
            f"💰 Доход: <b>{total_income:,.2f}</b> р.\n"
            f"💸 Расход: <b>{total_expense:,.2f}</b> р.\n"
            f"🔍 Баланс: <b>{balance:,.2f}</b> р."
        )

        # Визуализация
        fig, ax = plt.subplots(figsize=(6, 4))
        bars = ax.bar(["Доход", "Расход", "Баланс"], [total_income, total_expense, balance], color=["green", "red", "blue"])
        ax.set_title("Сводный отчет")
        ax.set_ylabel("Сумма (р.)")
        ax.grid(axis='y', linestyle='--', alpha=0.7)

        # Добавление числовых значений сверху столбцов
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f'{height:,.2f}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3),  # 3 points vertical offset
                        textcoords="offset points",
                        ha='center', va='bottom', fontsize=9, fontweight='bold')

        # Сохранение графика в временный файл
        file_path = save_plot_to_tempfile(fig, "summary_report")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения сначала
        await message.answer_photo(input_file)

        # Отправка текста после изображения
        await message.answer(summary_report, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации сводного отчета: {e}")
        await message.answer("❌ **Ошибка генерации сводного отчета. Попробуйте позже.**")
        return

    # Отчет по категориям с визуализацией
    try:
        category_report = data.groupby(["Категория", "Тип"])["Сумма"].sum().unstack(fill_value=0)

        # Разделение доходов и расходов
        income_categories = category_report.get("доход", pd.Series()).sort_values(ascending=False)
        expense_categories = category_report.get("расход", pd.Series()).sort_values(ascending=False)

        # Установка порога для исключения близких к нулю значений
        THRESHOLD = 1.0  # Можно изменить в зависимости от данных
        income_categories = income_categories[income_categories > THRESHOLD]
        expense_categories = expense_categories[expense_categories > THRESHOLD]

        # Формирование текстового отчета
        category_report_str = "<b>📂 Отчет по категориям:</b>\n"

        if not income_categories.empty:
            category_report_str += "<b>Доход:</b>\n"
            for category, value in income_categories.items():  # Используем items() вместо iteritems()
                category_report_str += f"  • {category}: <b>{value:,.2f}</b> р.\n"

        if not expense_categories.empty:
            category_report_str += "<b>Расход:</b>\n"
            for category, value in expense_categories.items():  # Используем items() вместо iteritems()
                category_report_str += f"  • {category}: <b>{value:,.2f}</b> р.\n"

        # Визуализация
        fig, ax = plt.subplots(figsize=(10, 8))

        # Объединяем доходы и расходы для графика
        combined_categories = pd.concat([income_categories, expense_categories])
        combined_categories = combined_categories.sort_values(ascending=False)

        # Определение цветов для доходов и расходов
        colors = ['green'] * len(income_categories) + ['red'] * len(expense_categories)

        bars = ax.barh(combined_categories.index, combined_categories.values, color=colors)
        ax.set_title("Отчет по категориям")
        ax.set_xlabel("Сумма (р.)")
        ax.set_ylabel("Категория")
        plt.tight_layout()

        # Добавление числовых значений справа от столбцов
        for bar in bars:
            width = bar.get_width()
            ax.annotate(f'{width:,.2f}',
                        xy=(width, bar.get_y() + bar.get_height() / 2),
                        xytext=(3, 0),  # 3 points horizontal offset
                        textcoords="offset points",
                        ha='left', va='center', fontsize=9, fontweight='bold')

        # Добавление легенды для обозначения типов
        import matplotlib.patches as mpatches
        income_patch = mpatches.Patch(color='green', label='Доход')
        expense_patch = mpatches.Patch(color='red', label='Расход')
        ax.legend(handles=[income_patch, expense_patch])

        # Сохранение графика в временный файл
        file_path = save_plot_to_tempfile(fig, "category_report")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения сначала
        await message.answer_photo(input_file)

        # Отправка текста после изображения
        await message.answer(category_report_str, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации отчета по категориям: {e}")
        await message.answer("❌ **Ошибка генерации отчета по категориям. Попробуйте позже.**")
        return

    # Динамика по месяцам с визуализацией
    try:
        data["Год-Месяц"] = data["Дата"].dt.to_period("M")
        monthly_income = data[data["Тип"] == "доход"].groupby("Год-Месяц")["Сумма"].sum()
        monthly_expense = data[data["Тип"] == "расход"].groupby("Год-Месяц")["Сумма"].sum()
        monthly_balance = monthly_income - monthly_expense

        monthly_report_str = "<b>📈 Динамика по месяцам:</b>\n"
        all_months = sorted(set(monthly_income.index).union(monthly_expense.index))
        for month in all_months:
            income = monthly_income.get(month, 0)
            expense = monthly_expense.get(month, 0)
            balance = income - expense
            monthly_report_str += (
                f"• <b>{month}</b>:\n"
                f"    Доход: <b>{income:,.2f}</b> р.\n"
                f"    Расход: <b>{expense:,.2f}</b> р.\n"
                f"    Баланс: <b>{balance:,.2f}</b> р.\n"
            )

        # Визуализация
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(monthly_income.index.astype(str), monthly_income.values, label="Доход", color="green", marker='o')
        ax.plot(monthly_expense.index.astype(str), monthly_expense.values, label="Расход", color="red", marker='o')
        ax.plot(monthly_balance.index.astype(str), monthly_balance.values, label="Баланс", color="blue", marker='o')
        ax.set_title("Динамика по месяцам")
        ax.set_xlabel("Месяц")
        ax.set_ylabel("Сумма (р.)")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.7)
        plt.xticks(rotation=45)
        plt.tight_layout()

        # Сохранение графика в временный файл
        file_path = save_plot_to_tempfile(fig, "monthly_dynamics")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения сначала
        await message.answer_photo(input_file)

        # Отправка текста после изображения
        await message.answer(monthly_report_str, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации динамического отчета: {e}")
        await message.answer("❌ **Ошибка генерации динамического отчета. Попробуйте позже.**")
        return

    # Топ-5 операций с визуализацией
    try:
        grouped_expenses = (
            data[data["Тип"] == "расход"]
            .groupby("Описание")["Сумма"]
            .sum()
            .reset_index()
            .nlargest(5, "Сумма")
        )
        grouped_income = (
            data[data["Тип"] == "доход"]
            .groupby("Описание")["Сумма"]
            .sum()
            .reset_index()
            .nlargest(5, "Сумма")
        )

        top_expenses_str = "<b>📋 Топ-5 расходов:</b>\n"
        for _, row in grouped_expenses.iterrows():
            top_expenses_str += f"• {row['Описание']}: <b>{row['Сумма']:,.2f}</b> р.\n"

        top_income_str = "<b>📋 Топ-5 доходов:</b>\n"
        for _, row in grouped_income.iterrows():
            top_income_str += f"• {row['Описание']}: <b>{row['Сумма']:,.2f}</b> р.\n"

        # Визуализация
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        # Топ-5 расходов
        bars_expense = axes[0].barh(grouped_expenses["Описание"], grouped_expenses["Сумма"], color="red")
        axes[0].set_title("Топ-5 расходов")
        axes[0].set_xlabel("Сумма (р.)")
        axes[0].invert_yaxis()  # Чтобы самый большой был наверху
        for bar in bars_expense:
            width = bar.get_width()
            axes[0].annotate(f'{width:,.2f}',
                             xy=(width, bar.get_y() + bar.get_height() / 2),
                             xytext=(3, 0),  # 3 points horizontal offset
                             textcoords="offset points",
                             ha='left', va='center', fontsize=9, fontweight='bold')

        # Топ-5 доходов
        bars_income = axes[1].barh(grouped_income["Описание"], grouped_income["Сумма"], color="green")
        axes[1].set_title("Топ-5 доходов")
        axes[1].set_xlabel("Сумма (р.)")
        axes[1].invert_yaxis()
        for bar in bars_income:
            width = bar.get_width()
            axes[1].annotate(f'{width:,.2f}',
                             xy=(width, bar.get_y() + bar.get_height() / 2),
                             xytext=(3, 0),
                             textcoords="offset points",
                             ha='left', va='center', fontsize=9, fontweight='bold')

        plt.tight_layout()

        # Сохранение графика в временный файл
        file_path = save_plot_to_tempfile(fig, "top_operations")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения сначала
        await message.answer_photo(input_file)

        # Отправка текста после изображения
        await message.answer(top_expenses_str, parse_mode="HTML")
        await message.answer(top_income_str, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации топовых операций: {e}")
        await message.answer("❌ **Ошибка генерации топовых операций. Попробуйте позже.**")
        return

    # Создание инлайн-кнопки
    builder = InlineKeyboardBuilder()
    builder.button(text='📑 Дополнительные отчёты', callback_data='additional_reports')
    inline_kb = builder.as_markup()

    # Отправка инлайн-кнопки
    await message.answer("📋 Выберите дополнительные отчёты для просмотра:", reply_markup=inline_kb)
    
def register_handlers(dp: Dispatcher):
    dp.register_callback_query_handler(handle_additional_reports, lambda c: c.data == 'additional_reports')
    
async def handle_additional_reports(callback_query: types.CallbackQuery):
    """
    Обработчик для генерации дополнительных отчётов.
    """
    await callback_query.answer()  # Убираем "часики"

    # Предполагаем, что у вас есть доступ к данным за тот же период
    # Возможно, вам нужно передать параметры периода через callback data или хранить в контексте

    # Здесь для примера используем функцию load_report_data()
    data = load_report_data()

    if data.empty:
        await callback_query.message.answer("❌ **Нет данных для генерации дополнительных отчётов.**")
        return

    # Фильтрация данных по выбранному периоду должна быть реализована
    # Возможно, храните период в контексте или передаёте через callback data

    # Для упрощения примера предполагаем, что данные уже отфильтрованы

    # Внедряемые отчёты:
    # 1) Расчёт Коэффициента Сбережений
    # 3) Оценка Коэффициента Расходов
    # 4) Ежедневный Анализ Кэш-Флоу
    # 5) Обнаружение Необычных Расходов

    # 1) Расчёт Коэффициента Сбережений
    try:
        total_income = data[data["Тип"] == "доход"]["Сумма"].sum()
        total_expense = data[data["Тип"] == "расход"]["Сумма"].sum()
        savings = total_income - total_expense
        savings_rate = (savings / total_income) * 100 if total_income != 0 else 0

        # Визуализация
        fig, ax = plt.subplots(figsize=(6, 6))
        labels = ['Сбережения', 'Расходы']
        sizes = [savings, total_expense]
        colors = ['gold', 'red']
        ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
        ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
        ax.set_title("Коэффициент Сбережений")
        plt.tight_layout()

        # Сохранение графика во временный файл
        file_path = save_plot_to_tempfile(fig, "savings_rate")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения
        await callback_query.message.answer_photo(input_file)

        # Формирование текстового отчёта
        savings_report = (
            f"💰 <b>Коэффициент Сбережений:</b>\n"
            f"• Сбережения: <b>{savings:,.2f}</b> р.\n"
            f"• Коэффициент Сбережений: <b>{savings_rate:.2f}%</b>."
        )

        # Отправка текста после изображения
        await callback_query.message.answer(savings_report, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации Коэффициента Сбережений: {e}")
        await callback_query.message.answer("❌ **Ошибка генерации Коэффициента Сбережений. Попробуйте позже.**")
        return

    # 3) Оценка Коэффициента Расходов
    try:
        expense_categories = data[data["Тип"] == "расход"].groupby("Категория")["Сумма"].sum()
        expense_ratios = (expense_categories / total_income) * 100 if total_income != 0 else pd.Series()

        # Визуализация
        fig, ax = plt.subplots(figsize=(10, 6))
        expense_ratios.plot(kind='bar', color='orange', ax=ax)
        ax.set_title("Коэффициент Расходов по Категориям")
        ax.set_xlabel("Категория")
        ax.set_ylabel("Расход (%)")
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()

        # Сохранение графика во временный файл
        file_path = save_plot_to_tempfile(fig, "expense_ratio")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения
        await callback_query.message.answer_photo(input_file)

        # Формирование текстового отчёта
        expense_ratio_report = "<b>📊 Коэффициент Расходов по Категориям:</b>\n"
        for category, ratio in expense_ratios.items():
            expense_ratio_report += f"• {category}: <b>{ratio:.2f}%</b>\n"

        # Отправка текста после изображения
        await callback_query.message.answer(expense_ratio_report, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации Коэффициента Расходов: {e}")
        await callback_query.message.answer("❌ **Ошибка генерации Коэффициента Расходов. Попробуйте позже.**")
        return

    # 4) Ежедневный Анализ Кэш-Флоу
    try:
        # Агрегация доходов и расходов по дням
        daily_income = data[data["Тип"] == "доход"].groupby('Дата')["Сумма"].sum()
        daily_expense = data[data["Тип"] == "расход"].groupby('Дата')["Сумма"].sum()

        # Создание DataFrame
        daily_cash = pd.DataFrame({
            'Доход': daily_income,
            'Расход': daily_expense
        }).fillna(0)
        daily_cash['Баланс'] = daily_cash['Доход'] - daily_cash['Расход']

        # Визуализация
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(daily_cash.index, daily_cash['Доход'], label='Доход', color='green')
        ax.plot(daily_cash.index, daily_cash['Расход'], label='Расход', color='red')
        ax.plot(daily_cash.index, daily_cash['Баланс'], label='Баланс', color='blue')
        ax.set_title("Ежедневный Cash Flow")
        ax.set_xlabel("Дата")
        ax.set_ylabel("Сумма (р.)")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.7)
        plt.xticks(rotation=45)
        plt.tight_layout()

        # Сохранение графика во временный файл
        file_path = save_plot_to_tempfile(fig, "daily_cash_flow")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения
        await callback_query.message.answer_photo(input_file)

        # Формирование текстового отчёта
        daily_cash_report = "📅 <b>Ежедневный Cash Flow:</b>\n"
        for date, row in daily_cash.iterrows():
            daily_cash_report += (
                f"• <b>{date.strftime('%d.%m.%Y')}</b>:\n"
                f"    Доход: <b>{row['Доход']:,.2f}</b> р.\n"
                f"    Расход: <b>{row['Расход']:,.2f}</b> р.\n"
                f"    Баланс: <b>{row['Баланс']:,.2f}</b> р.\n"
            )

        # Отправка текста после изображения
        await callback_query.message.answer(daily_cash_report, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации Ежедневного Cash Flow отчёта: {e}")
        await callback_query.message.answer("❌ **Ошибка генерации Ежедневного Cash Flow отчёта. Попробуйте позже.**")
        return

    # 5) Обнаружение Необычных Расходов
    try:
        # Агрегация расходов по категориям
        expense_categories = data[data["Тип"] == "расход"].groupby("Категория")["Сумма"].sum()

        # Расчёт среднего и стандартного отклонения
        mean = expense_categories.mean()
        std = expense_categories.std()

        # Определение порога для необычных расходов (например, больше среднего + 2 стандартных отклонения)
        threshold = mean + 2 * std

        # Выявление необычных расходов
        unusual_expenses = expense_categories[expense_categories > threshold]

        # Визуализация
        fig, ax = plt.subplots(figsize=(10, 6))
        expense_categories.plot(kind='bar', color='skyblue', ax=ax, label='Расходы')
        if not unusual_expenses.empty:
            unusual_expenses.plot(kind='bar', color='red', ax=ax, label='Необычные Расходы')
        ax.set_title("Расходы по Категориям с Необычными Расходами")
        ax.set_xlabel("Категория")
        ax.set_ylabel("Сумма (р.)")
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.7)
        plt.tight_layout()

        # Сохранение графика во временный файл
        file_path = save_plot_to_tempfile(fig, "unusual_expenses")

        # Создание объекта FSInputFile
        input_file = FSInputFile(file_path)

        # Отправка изображения
        await callback_query.message.answer_photo(input_file)

        # Формирование текстового отчёта
        if not unusual_expenses.empty:
            unusual_report = "<b>⚠️ Необычные Расходы:</b>\n"
            for category, amount in unusual_expenses.items():
                unusual_report += f"• {category}: <b>{amount:,.2f}</b> р. (Превышение порога)\n"
        else:
            unusual_report = "<b>✅ Не обнаружено необычных расходов.</b>"

        # Отправка текста после изображения
        await callback_query.message.answer(unusual_report, parse_mode="HTML")

        # Удаление временного файла
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Ошибка при удалении временного файла '{file_path}': {e}")

    except Exception as e:
        logging.error(f"Ошибка при генерации Обнаружения Необычных Расходов: {e}")
        await callback_query.message.answer("❌ **Ошибка генерации Обнаружения Необычных Расходов. Попробуйте позже.**")
        return
