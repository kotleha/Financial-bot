import csv
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials

# Функция для сохранения дохода в CSV
def save_income_to_csv(amount, category, status, description):
    with open('income_data.csv', 'a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([amount, category, status, description])

# Функция для сохранения в Google Sheets
def save_income_to_sheets(amount, category, status, description):
    creds = Credentials.from_service_account_file('/home/sexxlexx/Desktop/Financial-Bot/table-money-8ae6e0a39eab.json', scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build('sheets', 'v4', credentials=creds)
    
    spreadsheet_id = 'your_spreadsheet_id'
    range_ = 'Sheet1!A1'
    
    values = [[amount, category, status, description]]
    body = {
        'values': values
    }
    
    # Добавляем данные в таблицу Google Sheets
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption="RAW",
        body=body
    ).execute()
