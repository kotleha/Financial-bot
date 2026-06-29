from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.spending_limits import (
    default_spending_limit_config,
    resolve_category_limit,
    spending_limit_config_to_dict,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.spending_limit_service import (
    SPENDING_LIMITS_SETTINGS_KEY,
    SpendingLimitService,
)
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from financial_bot.app.storage.repositories.setting_repository import SettingRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/spending-limit-seed.sqlite3"
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
async def test_seed_initial_data_creates_default_spending_limit_config(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        stored = await SettingRepository(session).get_value(SPENDING_LIMITS_SETTINGS_KEY)
        config = await SpendingLimitService(session, settings).get_config()
        await session.commit()

    assert stored is not None
    assert config.thresholds == (50, 80, 100)
    assert resolve_category_limit(config, category_code="groceries", month=6).amount == 7_000_000
    assert resolve_category_limit(config, category_code="taxes", month=6).has_no_limit


@pytest.mark.asyncio
async def test_seed_initial_data_does_not_overwrite_existing_spending_limit_config(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    custom_config = spending_limit_config_to_dict(default_spending_limit_config())
    custom_config["categories"]["groceries"]["amount"] = 12_345

    async with session_factory() as session:
        await SettingRepository(session).set_value(SPENDING_LIMITS_SETTINGS_KEY, custom_config)
        await seed_initial_data(session, settings)
        config = await SpendingLimitService(session, settings).get_config()
        await session.commit()

    assert resolve_category_limit(config, category_code="groceries", month=6).amount == 12_345
