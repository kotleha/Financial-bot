from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.spending_limits import LimitRuleKind, resolve_category_limit
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/spending-limit-config.sqlite3"
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
async def test_spending_limit_service_updates_category_rules(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = SpendingLimitService(session, settings)

        monthly_config = await service.set_monthly_limit(
            category_code="groceries",
            amount=80_000 * 100,
        )
        no_limit_config = await service.set_no_limit(category_code="taxes")
        target_config = await service.set_savings_target(
            category_code="investments_savings",
            amount=35_000 * 100,
        )
        seasonal_config = await service.set_utilities_seasonal_limits(
            summer_amount=9_000 * 100,
            winter_amount=16_000 * 100,
        )
        generic_seasonal_config = await service.set_seasonal_limits(
            category_code="utilities",
            summer_amount=8_000 * 100,
            winter_amount=15_000 * 100,
        )
        await session.commit()

    assert resolve_category_limit(monthly_config, category_code="groceries", month=6).amount == (
        80_000 * 100
    )
    assert resolve_category_limit(no_limit_config, category_code="taxes", month=6).has_no_limit
    target = resolve_category_limit(
        target_config,
        category_code="investments_savings",
        month=6,
    )
    assert target.kind == LimitRuleKind.SAVINGS_TARGET
    assert target.amount == 35_000 * 100
    assert resolve_category_limit(seasonal_config, category_code="utilities", month=6).amount == (
        9_000 * 100
    )
    assert resolve_category_limit(seasonal_config, category_code="utilities", month=1).amount == (
        16_000 * 100
    )
    assert resolve_category_limit(
        generic_seasonal_config,
        category_code="utilities",
        month=6,
    ).amount == (8_000 * 100)
    assert resolve_category_limit(
        generic_seasonal_config,
        category_code="utilities",
        month=1,
    ).amount == (15_000 * 100)
