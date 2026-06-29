from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.spending_limit_alert_repository import (
    SpendingLimitAlertRepository,
)
from financial_bot.app.storage.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/transaction-limit-alerts.sqlite3"
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
async def test_transaction_limit_alerts_cross_50_80_100_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        limits = SpendingLimitService(session, settings)

        first = await transactions.create_from_category_sort_order(
            amount=35_000 * 100,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="35000 2",
        )
        await transactions.update_transaction(
            transaction_id=first.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 6, 1, 12, tzinfo=timezone),
        )
        first_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=first.id,
            recipient_telegram_id=1001,
        )
        repeated_first_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=first.id,
            recipient_telegram_id=1001,
        )

        second = await transactions.create_from_category_sort_order(
            amount=21_000 * 100,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="21000 2",
        )
        await transactions.update_transaction(
            transaction_id=second.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 6, 2, 12, tzinfo=timezone),
        )
        second_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=second.id,
            recipient_telegram_id=1001,
        )

        third = await transactions.create_from_category_sort_order(
            amount=16_000 * 100,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="16000 2",
        )
        await transactions.update_transaction(
            transaction_id=third.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 6, 3, 12, tzinfo=timezone),
        )
        third_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=third.id,
            recipient_telegram_id=1001,
        )
        repeated_third_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=third.id,
            recipient_telegram_id=1001,
        )
        await session.commit()

    assert [alert.threshold_percent for alert in first_alerts] == [50]
    assert repeated_first_alerts == ()
    assert [alert.threshold_percent for alert in second_alerts] == [80]
    assert [alert.threshold_percent for alert in third_alerts] == [100]
    assert third_alerts[0].overrun_amount == 200_000
    assert repeated_third_alerts == ()


@pytest.mark.asyncio
async def test_large_transaction_records_all_crossed_thresholds_but_returns_highest_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transaction = await TransactionService(session, settings).create_from_category_sort_order(
            amount=60_000 * 100,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="60000 2",
        )
        await TransactionService(session, settings).update_transaction(
            transaction_id=transaction.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 6, 1, 12, tzinfo=timezone),
        )
        alerts = await SpendingLimitService(
            session,
            settings,
        ).evaluate_transaction_threshold_alerts(
            transaction_id=transaction.id,
            recipient_telegram_id=1001,
        )
        category = await CategoryRepository(session).get_by_code("groceries")
        user = await UserRepository(session).get_by_telegram_id(1001)
        assert category is not None
        assert user is not None
        sent_thresholds = await SpendingLimitAlertRepository(session).list_sent_thresholds(
            period_start=datetime(2026, 6, 1, tzinfo=timezone),
            category_id=category.id,
            sent_to_user_id=user.id,
        )
        await session.commit()

    assert [alert.threshold_percent for alert in alerts] == [80]
    assert sent_thresholds == {50, 80}


@pytest.mark.asyncio
async def test_threshold_alerts_are_deduplicated_per_recipient(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transaction = await TransactionService(session, settings).create_from_category_sort_order(
            amount=35_000 * 100,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="35000 2",
        )
        limits = SpendingLimitService(session, settings)

        husband_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=transaction.id,
            recipient_telegram_id=1001,
        )
        wife_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=transaction.id,
            recipient_telegram_id=1002,
        )
        repeated_wife_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=transaction.id,
            recipient_telegram_id=1002,
        )
        await session.commit()

    assert [alert.threshold_percent for alert in husband_alerts] == [50]
    assert [alert.threshold_percent for alert in wife_alerts] == [50]
    assert repeated_wife_alerts == ()


@pytest.mark.asyncio
async def test_no_limit_and_savings_target_categories_do_not_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        taxes = await transactions.create_from_category_sort_order(
            amount=500_000 * 100,
            category_sort_order=17,
            payer_telegram_id=1001,
            raw_text="500000 17",
        )
        investments = await transactions.create_from_category_sort_order(
            amount=30_000 * 100,
            category_sort_order=15,
            payer_telegram_id=1001,
            raw_text="30000 15",
        )
        limits = SpendingLimitService(session, settings)
        tax_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=taxes.id,
            recipient_telegram_id=1001,
        )
        investment_alerts = await limits.evaluate_transaction_threshold_alerts(
            transaction_id=investments.id,
            recipient_telegram_id=1001,
        )
        await session.commit()

    assert tax_alerts == ()
    assert investment_alerts == ()
