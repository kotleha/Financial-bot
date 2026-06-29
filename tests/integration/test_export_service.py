from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind, resolve_month_period, resolve_period
from financial_bot.app.services.export_service import ExportService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.may_2026 import (
    EXPECTED_MAY_REPORT_RUB,
    MAY_2026_TRANSACTION_ROWS,
    seed_may_2026_transactions,
)

pd = pytest.importorskip("pandas")


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    pytest.importorskip("openpyxl")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/exports.sqlite3"
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
async def test_csv_export_contains_only_report_transactions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    period = resolve_month_period(year=2026, month=5, timezone=settings.timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        result = await ExportService(session, settings).create_csv_export(period)
        await session.commit()

    assert result is not None
    try:
        assert result.path.read_bytes().startswith(b"\xef\xbb\xbf")
        dataframe = pd.read_csv(result.path, sep=";")
        assert len(dataframe) == len(MAY_2026_TRANSACTION_ROWS)
        assert "internal_transfer" not in set(dataframe["category_code"])
        assert "category_owner_role" not in dataframe.columns
        assert dataframe["amount_rub"].sum() == EXPECTED_MAY_REPORT_RUB["total"]
        assert dataframe["report_amount_rub"].sum() == EXPECTED_MAY_REPORT_RUB["total"]
    finally:
        result.path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_xlsx_export_contains_required_sheets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    period = resolve_period(
        PeriodKind.YEAR,
        now=datetime(2026, 6, 1, tzinfo=ZoneInfo(settings.timezone)),
        timezone=settings.timezone,
    )

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        result = await ExportService(session, settings).create_xlsx_export(period)
        await session.commit()

    assert result is not None
    try:
        workbook = pd.ExcelFile(result.path)
        assert set(workbook.sheet_names) == {
            "transactions",
            "by_category",
            "by_payer",
            "income_transactions",
            "by_income_recipient",
            "by_income_category",
            "cashflow",
        }
        transactions = pd.read_excel(workbook, sheet_name="transactions")
        by_category = pd.read_excel(workbook, sheet_name="by_category")
        by_payer = pd.read_excel(workbook, sheet_name="by_payer")
        cashflow = pd.read_excel(workbook, sheet_name="cashflow")
        assert len(transactions) == len(MAY_2026_TRANSACTION_ROWS)
        assert "report_amount_rub" in transactions.columns
        assert "category_owner_role" not in transactions.columns
        assert "owner_role" not in by_category.columns
        assert set(by_payer["payer_role"]) == {"husband", "wife"}
        assert int(by_payer["amount_rub"].sum()) == EXPECTED_MAY_REPORT_RUB["total"]
        assert int(cashflow["expense_total_rub"][0]) == EXPECTED_MAY_REPORT_RUB["total"]
        assert int(cashflow["income_total_rub"][0]) == 0
    finally:
        result.path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_export_includes_corrections_with_signed_report_amount(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    period = resolve_month_period(year=2026, month=5, timezone=settings.timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        groceries = next(
            category
            for category in await transactions.list_category_options()
            if category.code == "groceries"
        )
        expense = await transactions.create_from_category_selection(
            amount=100_000,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="1000",
        )
        correction = await transactions.create_correction_from_category_selection(
            amount=30_000,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="bank_refund_event:1",
        )
        for transaction in (expense, correction):
            await transactions.update_transaction(
                transaction_id=transaction.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 5, 5, 12, tzinfo=timezone),
            )
        income = await transactions.create_income(
            amount=100_000 * 100,
            recipient_telegram_id=1001,
            raw_text="bank_income_event:1",
            comment="salary",
        )
        await transactions.update_transaction(
            transaction_id=income.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 5, 5, 13, tzinfo=timezone),
        )
        tables = await ExportService(session, settings).build_tables(period)
        await session.commit()

    rows_by_type = {row["type"]: row for row in tables.transactions}
    income_rows = {row["category_code"]: row for row in tables.income_transactions}
    assert set(rows_by_type) == {"expense", "correction"}
    assert rows_by_type["expense"]["amount_rub"] == 1000
    assert rows_by_type["expense"]["report_amount_rub"] == 1000
    assert rows_by_type["correction"]["amount_rub"] == 300
    assert rows_by_type["correction"]["report_amount_rub"] == -300
    assert income_rows["income_general"]["amount_rub"] == 100_000
    assert tables.by_income_category == [
        {
            "category_code": "income_general",
            "category_title": "Доходы",
            "amount_rub": 100_000,
            "share_percent": 100.0,
        }
    ]
    assert tables.cashflow[0]["period"] == "Май 2026"
    assert tables.cashflow[0]["income_total_rub"] == 100_000
    assert tables.cashflow[0]["expense_total_rub"] == 700
    assert tables.cashflow[0]["net_after_expenses_rub"] == 99_300
    assert "budget_net_savings_rub" in tables.cashflow[0]
    assert tables.by_category[0]["amount_rub"] == 700
    assert sum(row["amount_rub"] for row in tables.by_payer) == 700
