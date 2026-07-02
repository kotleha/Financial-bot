from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.report_service import ReportService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/reports.sqlite3"
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
async def test_month_report_excludes_internal_transfers_deleted_and_outside_period(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    report_now = datetime(2026, 5, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        groceries_category = next(
            category
            for category in await transactions.list_category_options()
            if category.code == "groceries"
        )

        groceries = await transactions.create_from_category_sort_order(
            amount=100000,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="1000 2",
        )
        await transactions.update_transaction(
            transaction_id=groceries.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 5, 5, 12, tzinfo=timezone),
        )
        groceries_refund = await transactions.create_correction_from_category_selection(
            amount=30000,
            category_id=groceries_category.id,
            payer_telegram_id=1001,
            raw_text="bank_refund_event:1",
            comment="refund",
        )
        await transactions.update_transaction(
            transaction_id=groceries_refund.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 5, 6, 12, tzinfo=timezone),
        )

        cafes = await transactions.create_from_free_text(
            text="ж 2000 кафе",
            current_payer_telegram_id=1001,
        )
        await transactions.update_transaction(
            transaction_id=cafes.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 5, 6, 12, tzinfo=timezone),
        )

        internal_transfer = await transactions.create_from_free_text(
            text="5000 сам себе",
            current_payer_telegram_id=1001,
        )
        await transactions.update_transaction(
            transaction_id=internal_transfer.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 5, 7, 12, tzinfo=timezone),
        )
        income = await transactions.create_income(
            amount=10000000,
            recipient_telegram_id=1001,
            raw_text="bank_income_event:1",
            comment="salary",
        )
        await transactions.update_transaction(
            transaction_id=income.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 5, 7, 13, tzinfo=timezone),
        )

        deleted = await transactions.create_from_category_sort_order(
            amount=700000,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="7000 2",
        )
        await transactions.update_transaction(
            transaction_id=deleted.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 5, 8, 12, tzinfo=timezone),
        )
        await transactions.delete_transaction(
            transaction_id=deleted.id,
            changed_by_telegram_id=1001,
        )

        outside_period = await transactions.create_from_category_sort_order(
            amount=900000,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="9000 2",
        )
        await transactions.update_transaction(
            transaction_id=outside_period.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 4, 30, 23, 59, tzinfo=timezone),
        )

        report = await ReportService(session, settings).build_period_report(
            PeriodKind.MONTH,
            now=report_now,
        )
        await session.commit()

    assert report.period.label == "Май 2026"
    assert report.total_amount == 270000
    assert [(line.role, line.amount, line.share_percent) for line in report.by_payer] == [
        ("husband", 70000, 25.9),
        ("wife", 200000, 74.1),
    ]
    assert {line.code: line.amount for line in report.by_category} == {
        "groceries": 70000,
        "restaurants_cafes": 200000,
    }


@pytest.mark.asyncio
async def test_month_report_can_be_filtered_by_accounting_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    report_now = datetime(2026, 6, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        categories = await transactions.list_category_options()
        groceries = next(category for category in categories if category.code == "groceries")
        restaurants = next(
            category for category in categories if category.code == "restaurants_cafes"
        )

        household = await transactions.create_from_category_selection(
            amount=10_000_00,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="дом 10000 продукты",
            scope=TransactionScope.HOUSEHOLD,
        )
        salon = await transactions.create_from_category_selection(
            amount=20_000_00,
            category_id=restaurants.id,
            payer_telegram_id=1002,
            raw_text="салон 20000 кафе",
            scope=TransactionScope.SALON,
        )
        salon_refund = await transactions.create_correction_from_category_selection(
            amount=5_000_00,
            category_id=restaurants.id,
            payer_telegram_id=1002,
            raw_text="bank_refund_event:salon",
            scope=TransactionScope.SALON,
        )
        for index, transaction in enumerate((household, salon, salon_refund), start=1):
            await transactions.update_transaction(
                transaction_id=transaction.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 6, index, 12, tzinfo=timezone),
            )

        all_report = await ReportService(session, settings).build_period_report(
            PeriodKind.MONTH,
            now=report_now,
        )
        salon_report = await ReportService(session, settings).build_period_report(
            PeriodKind.MONTH,
            now=report_now,
            scope=TransactionScope.SALON,
        )
        await session.commit()

    assert all_report.total_amount == 25_000_00
    assert salon_report.scope == TransactionScope.SALON
    assert salon_report.total_amount == 15_000_00
    assert [(line.role, line.amount, line.share_percent) for line in salon_report.by_payer] == [
        ("husband", 0, 0.0),
        ("wife", 15_000_00, 100.0),
    ]
    assert [(line.code, line.amount) for line in salon_report.by_category] == [
        ("restaurants_cafes", 15_000_00)
    ]


@pytest.mark.asyncio
async def test_category_totals_are_ordered_by_signed_amount_after_corrections(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    report_now = datetime(2026, 5, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        categories = await transactions.list_category_options()
        groceries = next(category for category in categories if category.code == "groceries")
        restaurants = next(
            category for category in categories if category.code == "restaurants_cafes"
        )

        rows = [
            (1_000_000, groceries.id, False),
            (900_000, groceries.id, True),
            (500_000, restaurants.id, False),
        ]
        for index, (amount, category_id, is_correction) in enumerate(rows, start=1):
            if is_correction:
                summary = await transactions.create_correction_from_category_selection(
                    amount=amount,
                    category_id=category_id,
                    payer_telegram_id=1001,
                    raw_text=f"refund {index}",
                )
            else:
                summary = await transactions.create_from_category_selection(
                    amount=amount,
                    category_id=category_id,
                    payer_telegram_id=1001,
                    raw_text=f"expense {index}",
                )
            await transactions.update_transaction(
                transaction_id=summary.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 5, index, 12, tzinfo=timezone),
            )

        report = await ReportService(session, settings).build_period_report(
            PeriodKind.MONTH,
            now=report_now,
        )
        await session.commit()

    assert [(line.code, line.amount) for line in report.by_category] == [
        ("restaurants_cafes", 500_000),
        ("groceries", 100_000),
    ]
