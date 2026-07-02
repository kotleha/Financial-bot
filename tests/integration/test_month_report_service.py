from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.month_report_service import MonthReportService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.may_2026 import EXPECTED_MAY_REPORT_RUB, seed_may_2026_transactions


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/month-report.sqlite3"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        bot_token="123456:secret-token",
        database_url="sqlite+aiosqlite:///unused.sqlite3",
        allowed_telegram_ids="1001,1002",
        default_currency="RUB",
        timezone="Asia/Barnaul",
        husband_telegram_id=1001,
        wife_telegram_id=1002,
    )


@pytest.mark.asyncio
async def test_month_report_v2_composes_report_budget_and_forecast(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    now = datetime(2026, 5, 20, 12, tzinfo=ZoneInfo(settings.timezone))

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        report = await MonthReportService(session, settings).build_month_report(now=now)
        await session.commit()

    assert report.period.label == "Май 2026"
    assert report.total_amount == EXPECTED_MAY_REPORT_RUB["total"] * 100
    assert report.income_total == 0
    assert report.net_after_expenses == -EXPECTED_MAY_REPORT_RUB["total"] * 100
    assert report.pace.elapsed_days == 20
    assert report.pace.day_count == 31
    assert report.pace.average_per_day == 2_616_200
    assert report.pace.forecast_amount == 81_102_800
    assert [(line.role, line.amount, line.share_percent) for line in report.by_payer] == [
        ("husband", EXPECTED_MAY_REPORT_RUB["husband_paid"] * 100, 69.4),
        ("wife", EXPECTED_MAY_REPORT_RUB["wife_paid"] * 100, 30.6),
    ]
    assert [line.code for line in report.top_categories] == [
        "utilities",
        "travel_vacation",
        "help_reserve",
        "groceries",
        "restaurants_cafes",
    ]
    assert report.other_categories_count == 4
    assert report.other_categories_amount > 0
    assert all(line.code != "internal_transfer" for line in report.top_categories)
    assert report.budget_risks[0].code == "utilities"
    assert report.overrun_total > 0
    assert report.net_savings == report.under_budget_pool - report.overrun_total
    assert report.savings_target_lines[0].code == "investments_savings"


@pytest.mark.asyncio
async def test_month_report_keeps_special_budget_categories_out_of_top_categories(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 6, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        groceries = await transactions.create_from_category_sort_order(
            amount=10_000_00,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="10000 2",
        )
        investments = await transactions.create_from_category_sort_order(
            amount=30_000_00,
            category_sort_order=15,
            payer_telegram_id=1001,
            raw_text="30000 15",
        )
        taxes = await transactions.create_from_category_sort_order(
            amount=80_000_00,
            category_sort_order=17,
            payer_telegram_id=1001,
            raw_text="80000 17",
        )
        income = await transactions.create_income(
            amount=150_000_00,
            recipient_telegram_id=1002,
            raw_text="/income 150000 зарплата",
            category_code="income_salary",
            comment="зарплата",
        )
        bonus = await transactions.create_income(
            amount=25_000_00,
            recipient_telegram_id=1001,
            raw_text="/income 25000 бонус",
            category_code="income_bonus",
            comment="бонус",
        )
        for transaction in (groceries, investments, taxes, income, bonus):
            await transactions.update_transaction(
                transaction_id=transaction.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 6, 10, 12, tzinfo=timezone),
            )

        report = await MonthReportService(session, settings).build_month_report(now=now)
        await session.commit()

    assert report.total_amount == 120_000_00
    assert report.income_total == 175_000_00
    assert report.net_after_expenses == 55_000_00
    assert [line.code for line in report.top_categories] == ["groceries"]
    assert [line.code for line in report.top_income_categories] == [
        "income_salary",
        "income_bonus",
    ]
    assert [
        (line.role, line.amount, line.share_percent) for line in report.income_by_recipient
    ] == [
        ("husband", 25_000_00, 14.3),
        ("wife", 150_000_00, 85.7),
    ]
    assert report.other_categories_count == 0
    assert [(line.code, line.spent_amount) for line in report.no_limit_lines] == [
        ("taxes", 80_000_00)
    ]
    assert [(line.code, line.actual_amount) for line in report.savings_target_lines] == [
        ("investments_savings", 30_000_00)
    ]
    assert report.budget_risks == ()


@pytest.mark.asyncio
async def test_scoped_month_report_hides_global_budget_lines(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 6, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        restaurants = next(
            category
            for category in await transactions.list_category_options()
            if category.code == "restaurants_cafes"
        )
        expense = await transactions.create_from_category_selection(
            amount=40_000_00,
            category_id=restaurants.id,
            payer_telegram_id=1001,
            raw_text="салон 40000 кафе",
            scope=TransactionScope.SALON,
        )
        income = await transactions.create_income(
            amount=100_000_00,
            recipient_telegram_id=1002,
            raw_text="manual_income:business",
            category_code="income_business",
            scope=TransactionScope.SALON,
        )
        for transaction in (expense, income):
            await transactions.update_transaction(
                transaction_id=transaction.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 6, 10, 12, tzinfo=timezone),
            )

        report = await MonthReportService(session, settings).build_month_report(
            now=now,
            scope=TransactionScope.SALON,
        )
        await session.commit()

    assert report.scope == TransactionScope.SALON
    assert report.total_amount == 40_000_00
    assert report.income_total == 100_000_00
    assert report.net_after_expenses == 60_000_00
    assert report.budget_risks == ()
    assert report.no_limit_lines == ()
    assert report.savings_target_lines == ()
    assert report.net_savings == 0
