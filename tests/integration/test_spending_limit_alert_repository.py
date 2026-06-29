from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base, SpendingLimitAlertModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.spending_limit_alert_repository import (
    SpendingLimitAlertRepository,
)
from financial_bot.app.storage.repositories.user_repository import UserRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/spending-limit-alerts.sqlite3"
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
async def test_spending_limit_alert_repository_records_and_deduplicates_thresholds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    period_start = datetime(2026, 6, 1, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transaction = await TransactionService(session, settings).create_from_category_sort_order(
            amount=35_000 * 100,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="35000 2",
        )
        category = await CategoryRepository(session).get_by_code("groceries")
        user = await UserRepository(session).get_by_telegram_id(1001)
        assert category is not None
        assert user is not None

        alerts = SpendingLimitAlertRepository(session)
        await alerts.add(
            SpendingLimitAlertModel(
                period_start=period_start,
                category_id=category.id,
                threshold_percent=50,
                transaction_id=transaction.id,
                sent_to_user_id=user.id,
            )
        )

        assert await alerts.list_sent_thresholds(
            period_start=period_start,
            category_id=category.id,
            sent_to_user_id=user.id,
        ) == {50}
        assert await alerts.has_sent_threshold(
            period_start=period_start,
            category_id=category.id,
            threshold_percent=50,
            sent_to_user_id=user.id,
        )
        assert not await alerts.has_sent_threshold(
            period_start=period_start,
            category_id=category.id,
            threshold_percent=80,
            sent_to_user_id=user.id,
        )

        with pytest.raises(IntegrityError):
            await alerts.add(
                SpendingLimitAlertModel(
                    period_start=period_start,
                    category_id=category.id,
                    threshold_percent=50,
                    transaction_id=transaction.id,
                    sent_to_user_id=user.id,
                )
            )
