# Financial Bot

This Telegram bot helps track income and expenses, store entries in CSV files and Google Sheets, and generate reports with charts.

## Usage

1. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set the required environment variables (see below).
3. Run the bot:
   ```bash
   python bot.py
   ```

### Environment variables

The bot relies on several environment variables that can be placed in a `.env` file or exported in your shell:

- `BOT_TOKEN` – Telegram bot token.
- `ALLOWED_USERS` – comma‑separated list of Telegram user IDs allowed to use the bot.
- `CREDENTIALS_PATH` – path to Google service account credentials JSON file.
- `SPREADSHEET_ID` – ID of the Google Spreadsheet used for storing data.

## Features

- Add income and expense records via commands and inline keyboards.
- Store data locally in monthly CSV files and in Google Sheets.
- Export CSV files for a selected period.
- Generate analytical reports with charts using pandas and matplotlib.

Python 3.10 or newer is recommended.
