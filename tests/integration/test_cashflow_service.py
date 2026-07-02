from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind
from financial_bot.app.domain.types import TransactionScope, TransactionSource
from financial_bot.app.services.cashflow_service import CashflowService
from financial_bot.app.services.report_service import ReportService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/cashflow.sqlite3"
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
async def test_cashflow_report_counts_income_separately_from_expense_report(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 6, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        groceries = next(
            category
            for category in await transactions.list_category_options()
            if category.code == "groceries"
        )
        expense = await transactions.create_from_category_selection(
            amount=30_000_00,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="30000",
            source=TransactionSource.CARD,
        )
        correction = await transactions.create_correction_from_category_selection(
            amount=5_000_00,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="bank_refund_event:1",
            source=TransactionSource.CARD,
        )
        income = await transactions.create_income(
            amount=100_000_00,
            recipient_telegram_id=1001,
            raw_text="bank_income_event:1",
            category_code="income_salary",
            comment="salary",
            source=TransactionSource.CARD,
        )
        bonus = await transactions.create_income(
            amount=25_000_00,
            recipient_telegram_id=1002,
            raw_text="/income 25000 бонус",
            category_code="income_bonus",
            comment="бонус",
            source=TransactionSource.UNKNOWN,
        )
        for index, item in enumerate((expense, correction, income, bonus), start=1):
            await transactions.update_transaction(
                transaction_id=item.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 6, index, 12, tzinfo=timezone),
            )

        cashflow = await CashflowService(session, settings).build_report(
            PeriodKind.MONTH,
            now=now,
        )
        expense_report = await ReportService(session, settings).build_period_report(
            PeriodKind.MONTH,
            now=now,
        )
        await session.commit()

    assert cashflow.period.label == "Июнь 2026"
    assert cashflow.income_total == 125_000_00
    assert cashflow.expense_total == 25_000_00
    assert cashflow.net_after_expenses == 100_000_00
    assert cashflow.budget_net_savings is not None
    assert [
        (line.role, line.amount, line.share_percent) for line in cashflow.income_by_recipient
    ] == [
        ("husband", 100_000_00, 80.0),
        ("wife", 25_000_00, 20.0),
    ]
    assert [
        (line.code, line.title, line.amount, line.share_percent)
        for line in cashflow.income_by_category
    ] == [
        ("income_salary", "Зарплата", 100_000_00, 80.0),
        ("income_bonus", "Премия/Бонус", 25_000_00, 20.0),
    ]
    assert expense_report.total_amount == 25_000_00
    assert {line.code: line.amount for line in expense_report.by_category} == {
        "groceries": 25_000_00
    }


@pytest.mark.asyncio
async def test_cashflow_report_can_be_filtered_by_accounting_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 6, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        groceries = next(
            category
            for category in await transactions.list_category_options()
            if category.code == "groceries"
        )
        household_expense = await transactions.create_from_category_selection(
            amount=30_000_00,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="дом 30000 продукты",
            scope=TransactionScope.HOUSEHOLD,
        )
        salon_expense = await transactions.create_from_category_selection(
            amount=40_000_00,
            category_id=groceries.id,
            payer_telegram_id=1002,
            raw_text="салон 40000 продукты",
            scope=TransactionScope.SALON,
        )
        household_income = await transactions.create_income(
            amount=100_000_00,
            recipient_telegram_id=1001,
            raw_text="manual_income:salary",
            category_code="income_salary",
            scope=TransactionScope.HOUSEHOLD,
        )
        salon_income = await transactions.create_income(
            amount=120_000_00,
            recipient_telegram_id=1002,
            raw_text="manual_income:business",
            category_code="income_business",
            scope=TransactionScope.SALON,
        )
        for index, transaction in enumerate(
            (household_expense, salon_expense, household_income, salon_income),
            start=1,
        ):
            await transactions.update_transaction(
                transaction_id=transaction.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 6, index, 12, tzinfo=timezone),
            )

        cashflow = await CashflowService(session, settings).build_report(
            PeriodKind.MONTH,
            now=now,
            scope=TransactionScope.SALON,
        )
        await session.commit()

    assert cashflow.scope == TransactionScope.SALON
    assert cashflow.income_total == 120_000_00
    assert cashflow.expense_total == 40_000_00
    assert cashflow.net_after_expenses == 80_000_00
    assert cashflow.budget_net_savings is None
    assert [
        (line.role, line.amount, line.share_percent) for line in cashflow.income_by_recipient
    ] == [
        ("husband", 0, 0.0),
        ("wife", 120_000_00, 100.0),
    ]
