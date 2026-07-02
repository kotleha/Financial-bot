# Family Finance Telegram Bot

Family Finance Telegram Bot is a clean-room project for fast family expense tracking in
Telegram. The core model records who paid, the category, reports by period, charts,
exports, and operational safety around drafts/editing.

## Current Status

The project is being implemented slice by slice.

Completed:

- Slice 0: old repository audit and clean-room decision.
- Slice 1: project bootstrap.
- Slice 2: typed settings and Telegram ID whitelist baseline.
- Slice 3: database models, Alembic migration, async session helpers, repositories.
- Slice 4: idempotent seed for users, categories, and aliases.
- Slice 5: basic aiogram runtime, `/start`, auth middleware wiring, main menu.
- Slice 6: amount-first expense draft and category-button transaction creation.
- Slice 7: numeric category selection and `amount category-number` input.
- Slice 8: free-text parser, aliases, internal-transfer exclusion, unknown-category rejection.
- Slice 9: batch input with partial failures and cancel-all soft delete.
- Slice 10: transaction action buttons, edit/delete, `/undo`, `/repeat`, audit log writes.
- Slice 11: period reports for week/month/quarter/half-year/year and Russian aliases.
- Slice 12: May 2026 fixture acceptance values for payer and category totals.
- Slice 13: payer/category-owner report was superseded by payer-focused reporting after
  the category ownership product logic was removed.
- Slice 14: removed after product decision; all saved expenses must have a category.
- Slice 15: PNG charts for categories, cumulative spending, month compare, trend.
- Slice 16: CSV/XLSX export with required workbook sheets.
- Slice 17: optional Google Sheets export.
- Slice 18: reminder settings, active-recipient filtering, reminder text service, scheduler.
- Slice 19: Docker deployment, Compose config, SQLite backup script.
- Slice 20: GitHub Actions CI for Ruff and pytest.
- BI-06: HTTP bank SMS ingestion endpoint for iPhone Shortcuts.
- BI-07: bank event pending/retry tracking for missed Telegram confirmations.

## Requirements

- Python 3.12+.
- `uv` is recommended for local dependency management.

## Local Setup

With `uv`:

```bash
uv sync --extra dev
```

With standard Python tooling:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

Create local environment configuration:

```bash
cp .env.example .env
```

Do not put real secrets into tracked files.

Required configuration:

- `BOT_TOKEN`
- `DATABASE_URL`
- `ALLOWED_TELEGRAM_IDS`
- `DEFAULT_CURRENCY`
- `TIMEZONE`
- `HUSBAND_TELEGRAM_ID`
- `WIFE_TELEGRAM_ID`

Optional bank SMS parsing configuration:

- `BANK_SELF_COUNTERPARTY_ALIASES` - comma-separated labels for own-account transfer
  counterparties. Keep real values only in private `.env` files.
- `BANK_INGEST_HOST` and `BANK_INGEST_PORT` - bind address for the optional HTTP ingestion app.

## Verification

Run the baseline checks after every implementation slice:

```bash
python -m pytest
ruff check .
ruff format --check .
```

If you use `uv`, equivalent commands are:

```bash
uv run python -m pytest
uv run ruff check .
uv run ruff format --check .
```

Database migration smoke check:

```bash
alembic upgrade head
alembic current
```

Seed initial data after migrations:

```bash
.venv/bin/python scripts/seed_initial_data.py --env-file .env
```

Run the bot after configuring real secrets:

```bash
.venv/bin/python -m financial_bot.app.bot.main
```

Run the optional HTTP bank ingestion app after migrations and seed:

```bash
family-finance-bank-ingest
```

It exposes:

- `GET /health`
- `POST /bank-events`

`POST /bank-events` expects `Authorization: Bearer <source-token>` and JSON:

```json
{
  "text": "redacted or real bank SMS text from the private device",
  "sender": "900",
  "received_at": "2026-06-26T12:00:00+07:00"
}
```

Source tokens are generated and stored server-side as hashes in `bank_event_sources`; do not put
the Telegram bot token or database credentials on the phone.

Create or rotate a bank event source token:

```bash
family-finance-bank-source --env-file .env --code husband-sber-ios --bank sber --owner-role husband
family-finance-bank-source --env-file .env --code husband-sber-ios --bank sber --owner-role husband --rotate
family-finance-bank-source --env-file .env --code wife-tbank-ios --bank tbank --owner-role wife
```

Use your own HTTPS reverse proxy or private network route for production bank ingestion. The
production source tokens are not tracked and must stay only in private server storage.

Main menu buttons:

- `➕ Расход`
- `➕ Доход`
- `🏦 Автоучёт`
- `📊 Отчёты`
- `💰 Бюджет`
- `⚙️ Настройки`

Reports menu buttons:

- `🧾 Итог месяца`
- `✅ Закрыть месяц`
- `📊 Месяц`
- `📊 Неделя`
- `📊 Квартал`
- `📊 Полгода`
- `📊 Год`
- `💸 Денежный поток`
- `📈 Категории`
- `📉 Динамика месяца`
- `📆 Сравнить`
- `👥 Кто платил`
- `↩️ Главное меню`

Budget menu buttons:

- `📋 Сводка бюджета`
- `🧾 Лимиты`
- `🏦 Копилка`
- `⚙️ Настроить лимиты`
- `↩️ Главное меню`

`⚙️ Настроить лимиты` opens a button-driven limit editor:

1. choose category;
2. choose monthly limit, no limit, savings target, or summer/winter mode for `ЖКХ`;
3. enter the amount;
4. confirm the preview.

After a confirmed change, both family users are notified. The old command syntax still works.

Auto-accounting menu buttons:

- `🩺 Состояние автоучёта`
- `🔎 Проверить источники`
- `🔁 Повторить отправку ожидающих`
- `🧠 Правила категорий`
- `ℹ️ Как работает автоучёт`
- `↩️ Главное меню`

`🩺 Состояние автоучёта` and `🔎 Проверить источники` show a 30-day auto-accounting quality
dashboard: source health, received bank events, autosaved and manually confirmed expenses,
non-expense events, delivery issues, unknown formats, learned-rule mode counts, and top learned
merchant rules. Raw SMS text and tokens are not exposed. `🔁 Повторить отправку ожидающих` resends
pending confirmation cards for the current user. The old `⏳ Ожидают подтверждения` text is still
accepted as an alias.

Settings menu buttons:

- `🏷 Категории`
- `🔤 Алиасы`
- `🧾 Лимиты`
- `⏰ Напоминания`
- `🏦 Банки`
- `↩️ Главное меню`

`🏷 Категории` opens category settings: choose an active expense category, rename it, or add a
recognition alias. `🔤 Алиасы` opens the same category list with alias setup in mind. Category
codes, numbers, transaction history, reports, and limits stay attached to the category. Creating,
hiding, deleting, and reordering categories are intentionally deferred to a separate safer slice.
The bot shows contextual hints in these dialogs: what a category rename changes, how aliases help
manual input and bank SMS recognition, and why very short or numeric aliases are rejected.

Income can be entered manually from `➕ Доход` or `/income`, and bank SMS income can be confirmed
with `Учесть доход`. Income appears in the separate cashflow report and export sheets. It does not
change expense reports, spending limits, or expense category charts.

Bank SMS refund messages can be confirmed as separate correction transactions. Corrections reduce
expense totals for reports, budgets, charts, and exports without rewriting the original expense.

Bank SMS parsers currently cover Sber/`900`, VTB, and T-Bank. Keep separate source tokens and
iPhone automations per bank and owner.

Expenses can optionally carry an accounting scope. By default every operation is `Дом`. Prefix
manual input with `салон` when the expense or income belongs to salon/business accounting:
`салон 3500 18 бумага`, `салон 900 такси`, `/income салон 70000 услуги`. Categories still answer
"what was it?", while the scope answers "for which activity?". Bank event cards also have
`Дом`/`Салон` buttons before or after autosave.

Current categories:

1. ЖКХ
2. Продукты
3. Подписки/Связь/Интернет
4. Авто/Транспорт/Такси
5. Питомцы
6. Рестораны/Кафе
7. Дети (Образование/Спорт)
8. Косметология/Медицина
9. Одежда/Обувь
10. Фитнес/Спорт
11. Хобби
12. Дом/Участок
13. Подарки/Развлечения/Праздники
14. Путешествия/Отдых
15. Инвестиции/Накопления
16. Помощь/Резерв
17. Налоги
18. Канцелярия/Расходники

`internal_transfer` is a hidden service category for inputs such as `сам себе`; it is not
shown in the category keyboard and is excluded from reports.

Current expense-entry commands:

- `/edit` shows the latest active operation with action buttons.
- `/undo` soft-deletes the latest active operation created by the current user.
- `/repeat` repeats the latest active operation for today.
- `/income 100000 зарплата`, `доход 25000 аванс`, or `+15000 проект` creates a manual
  income operation. Supported income sources are salary, advance, bonus, business/projects,
  debt return, and other income.
- `салон 3500 канцелярия`, `дом 900 такси`, or `ж салон 4200 кафе` creates scoped expenses.
  Scope is optional; omitted scope means `Дом`.
- `/bank <sms text>` parses and stores a redacted bank SMS event for manual testing. Expense
  candidates can then be confirmed with inline buttons, assigned to another category, ignored,
  or marked as an internal transfer.
- Bank income SMS can be confirmed as income with `Учесть доход`. Income is shown in `/cashflow`,
  but stays out of expense reports, spending limits, category charts, and expense exports.
- Bank refund SMS can be confirmed as a correction for a selected expense category.
- `/bank pending` or `/bank_pending` shows bank events that still wait for confirmation and resends
  their Telegram action cards.
- `/cashflow` or `денежный поток` sends a PNG cashflow dashboard for the selected period: income
  sources, recipients, expenses, and the net amount after expenses. Text fallback is used when
  there is no data for the period.
- `/chart cashflow month` builds the same cashflow dashboard explicitly. `week`, `quarter`,
  `halfyear`, and `year` are supported.
- `/week`, `/month`, `/quarter`, `/halfyear`, `/year` and Russian period aliases send a PNG
  dashboard for the selected period. The dashboard groups totals, category structure, period
  dynamics, and payer split in one readable image.
- `/month` keeps the richer monthly dashboard with spending pace, forecast, category split, budget
  risks, and estimated savings by current limits.
- `/dashboard` or `/status` sends the monthly PNG dashboard. `/dashboard week`,
  `/dashboard quarter`, `/dashboard halfyear`, and `/dashboard year` are also supported.
- PNG dashboards use a dark Telegram-friendly theme by default: background `#0e1621`, dark panels
  and axes, and light text. Telegram bot messages do not expose the user's app/device theme to the
  backend, so fully automatic per-device theme matching is not available in the normal chat flow.
- Generated PNG reports are deleted after Telegram upload; stale generated chart files older than
  24 hours are cleaned from the bot temp directory before new chart generation.

Bank confirmations now keep simple learned category rules: after a user confirms a bank expense
with a merchant and category, future events from the same bank and merchant can suggest that
category with the hint `по прошлым подтверждениям`. Learned rules have explicit modes:
`только подсказка`, `автосохранение`, and `отключено`. After repeated confirmations a new rule can
move to autosave mode; suggest-only and disabled rules never create expenses by themselves. If a
learned rule conflicts with a parser category hint, the bot asks for confirmation instead of
autosaving. The autosaved card has buttons to fix the category, mark it as an internal transfer,
delete the autosaved expense, or disable the rule.
Bank cards explain why a category was suggested: SMS parser hint, previous confirmations, or manual
choice. Internal-transfer and income cards also state clearly that they do not affect expense
limits or expense category charts.

Learned rules can be managed from `🏦 Автоучёт` -> `🧠 Правила категорий` or from settings
`🏦 Банки`. Each family user sees only their own rules. A rule can be opened, assigned to another
category, switched between suggest-only/autosave mode, or disabled.

Budget and limit reports explain the difference between a spending limit, a no-limit category, and
a savings target. The estimated savings pool is calculated as remaining limit amounts minus
overruns; categories without limits are counted in expenses but not in that estimate.

Internal transfers are supported in free text and excluded from reports:

- `5000 сам себе`
- `5000 себе`
- `5000 жене`
- `5000 перевод жене`
- `5000 мужу перевёл`
- `5000 скинул супруге`
- `20000 99`

Current report commands:

- `/summary`, `/month_summary`, `итог месяца` — smart monthly text summary with expenses, income,
  cashflow, limits, overruns, and estimated savings
- `/week`, `/month`, `/quarter`, `/halfyear`, `/year` — visual period dashboards
- `неделя`, `месяц`, `квартал`, `полгода`, `год` — visual period dashboards
- `/report text month`, `/report text quarter` — text period reports
- `/categories`, `категории` — category chart for the current month
- `/payers`, `кто платил` — visual payer report for the current month
- `/dashboard week`, `/dashboard month`, `/dashboard quarter`, `/dashboard halfyear`,
  `/dashboard year`
- `/chart categories week`, `/chart categories month`, `/chart categories quarter`,
  `/chart categories halfyear`, `/chart categories year`
- `/chart week`, `/chart month`, `/chart quarter`, `/chart halfyear`, `/chart year`
- `/chart cumulative month`
- `/limits`, `лимиты` — current limit settings and edit examples
- `/budget`, `бюджет` — full monthly fact-vs-limit report
- `/savings`, `копилка` — limit-based savings estimate, not a real cash balance
- `/compare apr may`, `/trend 6m`, `/trend 12m`
- report menu buttons also open payer, compare-months, and trend charts
- `/export csv may`, `/export xlsx may`, `/export xlsx 2026`
- `/sheets export may`
- `/reminders`, `/reminders on`, `/reminders off`, `/reminders time 21:00`

Expense, category, payer, dashboard, cumulative, compare, trend, and cashflow reports can be
filtered by accounting scope. Add `дом`, `салон`, or `all`/`все` to the command:

- `/month salon`, `месяц салон` — visual monthly dashboard only for salon transactions
- `/summary салон`, `итог месяца салон` — scoped smart monthly text summary
- `/cashflow salon`, `/cashflow quarter salon` — scoped cashflow dashboard
- `/chart categories month salon`, `/dashboard week дом`, `/trend 6m salon`

Spending limits and the savings estimate stay in the all-scope family report. Scoped reports show
their own expenses/income/cashflow and state that budget limits are calculated only in the combined
report.

XLSX and Google Sheets exports include separate sheets for expense transactions, expense category
totals, payer totals, income transactions, income recipients, income categories, and cashflow
summary. CSV export is a single transaction-style file with expense/correction rows plus income
rows; internal transfers are excluded.
