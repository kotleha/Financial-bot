"""aiogram routers."""

from aiogram import Router

from financial_bot.app.bot.routers.auto_accounting_health import (
    router as auto_accounting_health_router,
)
from financial_bot.app.bot.routers.bank_events import router as bank_events_router
from financial_bot.app.bot.routers.bank_learning import router as bank_learning_router
from financial_bot.app.bot.routers.cashflow import router as cashflow_router
from financial_bot.app.bot.routers.category_settings import router as category_settings_router
from financial_bot.app.bot.routers.charts import router as charts_router
from financial_bot.app.bot.routers.expense_entry import router as expense_entry_router
from financial_bot.app.bot.routers.exports import router as exports_router
from financial_bot.app.bot.routers.google_sheets import router as google_sheets_router
from financial_bot.app.bot.routers.income_entry import router as income_entry_router
from financial_bot.app.bot.routers.menu import router as menu_router
from financial_bot.app.bot.routers.reminders import router as reminders_router
from financial_bot.app.bot.routers.reports import router as reports_router
from financial_bot.app.bot.routers.spending_limits import router as spending_limits_router
from financial_bot.app.bot.routers.start import router as start_router


def get_routers() -> tuple[Router, ...]:
    return (
        start_router,
        bank_learning_router,
        menu_router,
        auto_accounting_health_router,
        category_settings_router,
        cashflow_router,
        reports_router,
        charts_router,
        spending_limits_router,
        income_entry_router,
        bank_events_router,
        exports_router,
        google_sheets_router,
        reminders_router,
        expense_entry_router,
    )
