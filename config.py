import os
from dotenv import load_dotenv

load_dotenv()  # Загружаем переменные из .env

# Получаем токен и список разрешённых пользователей
BOT_TOKEN = os.getenv('BOT_TOKEN')
ALLOWED_USERS = list(map(int, os.getenv('ALLOWED_USERS').split(',')))
