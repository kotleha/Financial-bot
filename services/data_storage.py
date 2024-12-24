import csv
import logging
import os
from datetime import datetime
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

# Загружаем переменные окружения из .env
load_dotenv()

# Настраиваем логирование для отладки
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Переменные окружения
CREDENTIALS_PATH = os.getenv('CREDENTIALS_PATH')
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')

# Названия столбцов для структуры таблиц
REQUIRED_HEADERS = ["Дата", "Категория", "Сумма", "Тип", "Описание", "Статус"]

def ensure_csv_structure():
    """
    Проверяет структуру локального CSV файла и создает его, если он отсутствует или некорректен.
    """
    if not os.path.exists('data.csv'):
        with open('data.csv', 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(REQUIRED_HEADERS)
        logging.info("CSV файл создан с необходимой структурой.")
    else:
        with open('data.csv', 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            headers = next(reader, None)
            if not headers or set(REQUIRED_HEADERS) - set(headers):
                # Если столбцы отсутствуют или некорректны, обновляем файл
                with open('data.csv', 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerow(REQUIRED_HEADERS)
                logging.info("CSV файл обновлен с необходимой структурой.")

def get_month_csv(date):
    """
    Возвращает путь к файлу CSV для текущего месяца в формате csv_reports/NN_MonthName_YYYY.csv.
    Если файл не существует, создаёт новый с заголовками.
    Если файл существует, проверяет заголовки и добавляет их при необходимости.
    """
    # Определяем номер месяца, название месяца и год
    month_number = datetime.strptime(date, "%d.%m.%Y").strftime("%m")
    month_name = datetime.strptime(date, "%d.%m.%Y").strftime("%B")
    year = datetime.strptime(date, "%d.%m.%Y").strftime("%Y")

    # Формируем путь к папке для CSV
    folder_path = "csv_reports"
    os.makedirs(folder_path, exist_ok=True)  # Создаём папку, если она не существует

    # Формируем полный путь к файлу
    file_name = f"{month_number}_{month_name}_{year}.csv"
    file_path = os.path.join(folder_path, file_name)

    # Проверяем, существует ли файл
    if not os.path.exists(file_path):
        with open(file_path, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(REQUIRED_HEADERS)  # Пишем заголовки
        logging.info(f"Создан новый CSV файл: {file_path}")
    else:
        # Проверяем заголовки, если файл существует
        with open(file_path, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            headers = next(reader, None)
            if not headers or set(REQUIRED_HEADERS) - set(headers):
                # Если заголовки отсутствуют или некорректны, обновляем их
                with open(file_path, 'w', newline='', encoding='utf-8') as file:
                    writer = csv.writer(file)
                    writer.writerow(REQUIRED_HEADERS)
                logging.info(f"Обновлены заголовки в существующем CSV файле: {file_path}")

    return file_path

def get_month_sheet(service, spreadsheet_id, date):
    """
    Проверяет наличие листа с названием месяца (в формате NN_MonthName_YYYY). 
    Если его нет, создаёт новый лист.
    Если лист существует, проверяет заголовки и добавляет их при необходимости.
    """
    try:
        # Определяем номер месяца, название месяца и год
        month_number = datetime.strptime(date, "%d.%m.%Y").strftime("%m")
        month_name = datetime.strptime(date, "%d.%m.%Y").strftime("%B")
        year = datetime.strptime(date, "%d.%m.%Y").strftime("%Y")

        # Формируем название листа
        sheet_name = f"{month_number}_{month_name}_{year}"

        # Получаем список листов
        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = spreadsheet.get("sheets", [])

        # Проверяем, существует ли лист с названием месяца
        for sheet in sheets:
            if sheet["properties"]["title"] == sheet_name:
                logging.info(f"Лист с названием '{sheet_name}' уже существует.")

                # Проверяем заголовки на существующем листе
                result = service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f'{sheet_name}!A1:F1'
                ).execute()
                headers = result.get('values', [[]])[0]  # Получаем первую строку заголовков

                # Если заголовки отсутствуют или некорректны, создаём их
                if not headers or set(REQUIRED_HEADERS) - set(headers):
                    body = {
                        'values': [REQUIRED_HEADERS]
                    }
                    service.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id,
                        range=f'{sheet_name}!A1:F1',
                        valueInputOption="RAW",
                        body=body
                    ).execute()
                    logging.info(f"Обновлены заголовки на существующем листе '{sheet_name}'.")
                else:
                    logging.info(f"Заголовки на листе '{sheet_name}' корректны.")
                return sheet_name

        # Если лист не найден, создаём его
        body = {
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": sheet_name
                        }
                    }
                }
            ]
        }
        service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
        logging.info(f"Создан новый лист с названием '{sheet_name}'.")

        # Добавляем заголовки сразу после создания листа
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f'{sheet_name}!A1:F1',
            valueInputOption="RAW",
            body={"values": [REQUIRED_HEADERS]}
        ).execute()
        logging.info(f"Заголовки добавлены на новый лист '{sheet_name}'.")

        return sheet_name
    except HttpError as error:
        logging.error(f"Ошибка при работе с Google Sheets API: {error}")
        raise

def ensure_google_sheets_structure(date):
    """
    Проверяет структуру Google Sheets и создаёт заголовки в листе текущего месяца.
    """
    try:
        creds = Credentials.from_service_account_file(
            CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build('sheets', 'v4', credentials=creds)

        # Определяем название текущего месяца
        month_name = datetime.strptime(date, "%d.%m.%Y").strftime("%B")

        # Проверяем или создаём лист
        sheet_name = get_month_sheet(service, SPREADSHEET_ID, month_name)

        # Проверяем заголовки на этом листе
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{sheet_name}!A1:F1'
        ).execute()
        headers = result.get('values', [[]])[0]  # Получаем первую строку заголовков

        # Если заголовки отсутствуют или некорректны, создаём их
        if not headers or set(REQUIRED_HEADERS) - set(headers):
            body = {
                'values': [REQUIRED_HEADERS]
            }
            service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f'{sheet_name}!A1:F1',
                valueInputOption="RAW",
                body=body
            ).execute()
            logging.info(f"Заголовки обновлены на листе '{sheet_name}'.")
        else:
            logging.info(f"Заголовки на листе '{sheet_name}' корректны.")
    except HttpError as error:
        logging.error(f"Ошибка при работе с Google Sheets API: {error}")
    except Exception as e:
        logging.error(f"Неизвестная ошибка: {e}")

def save_data_to_csv(date, category, amount, entry_type, description, status):
    """
    Сохраняет данные в CSV файл. Каждый месяц записывается в отдельный файл.
    Проверяет и преобразует данные перед записью.
    """
    try:
        # Валидация и преобразование данных
        date, category, amount, entry_type, description, status = validate_and_convert_data(
            date, category, amount, entry_type, description, status
        )

        # Получаем путь к файлу для текущего месяца
        file_path = get_month_csv(date)

        # Добавляем данные в файл
        with open(file_path, 'a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([date, category, amount, entry_type, description, status])
        logging.info(f"Данные успешно добавлены в файл: {file_path}")
    except Exception as e:
        logging.error(f"Ошибка при сохранении в CSV: {e}")

def save_data_to_sheets(date, category, amount, entry_type, description, status):
    """
    Сохраняет данные в Google Sheets. Каждый месяц записывается на отдельный лист
    с названием в формате NN_MonthName_YYYY.
    """
    try:
        # Валидация и преобразование данных
        date, category, amount, entry_type, description, status = validate_and_convert_data(
            date, category, amount, entry_type, description, status
        )

        # Создаём сервис
        creds = Credentials.from_service_account_file(
            CREDENTIALS_PATH,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build("sheets", "v4", credentials=creds)

        # Получаем название листа
        sheet_name = get_month_sheet(service, SPREADSHEET_ID, date)

        # Данные для записи
        values = [[date, category, amount, entry_type, description, status]]
        body = {
            "values": values
        }

        # Диапазон записи (например, A2:F2)
        range_ = f"{sheet_name}!A2:F2"

        # Добавляем данные
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=range_,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        logging.info(f"Данные успешно добавлены в лист '{sheet_name}'.")
    except Exception as e:
        logging.error(f"Ошибка при записи в Google Sheets: {e}")

def get_user_data_from_csv(user_id):
    data = []
    try:
        with open('data.csv', mode='r', encoding='utf-8') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                if int(row.get('user_id', 0)) == user_id:
                    data.append(row)
    except FileNotFoundError:
        # Логирование или обработка ошибки
        pass
    return data

def validate_and_convert_data(date, category, amount, entry_type, description, status):
    """
    Проверяет и преобразует типы данных для записи в таблицы.
    Возвращает кортеж значений в корректных типах.
    """
    try:
        # Проверка и преобразование даты
        date = datetime.strptime(date, "%d.%m.%Y").strftime("%d.%m.%Y")  # Убедимся, что дата корректна

        # Проверка категории
        if not isinstance(category, str) or not category:
            raise ValueError(f"Некорректная категория: {category}")

        # Проверка суммы
        amount = float(amount)  # Преобразуем сумму в float

        # Проверка типа (доход/расход)
        if entry_type not in ["доход", "расход"]:
            raise ValueError(f"Некорректный тип: {entry_type}")

        # Проверка описания
        if not isinstance(description, str):
            raise ValueError(f"Некорректное описание: {description}")

        # Проверка статуса
        status = status.lower()
        if status not in ["активный", "пассивный"]:
            raise ValueError(f"Некорректный статус: {status}")

        return date, category, amount, entry_type, description, status
    except Exception as e:
        logging.error(f"Ошибка валидации данных: {e}")
        raise
