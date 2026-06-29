from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.services.alias_service import AliasService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base, CategoryAliasModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/alias-service.sqlite3"
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
async def test_alias_service_matches_complete_tokens_and_phrases(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = AliasService(session)

        groceries = await service.resolve_category("3500 продукты магнит")
        mobile = await service.resolve_category("1200 мобильная связь")
        not_home = await service.resolve_category("500 домик для игрушек")
        not_auto = await service.resolve_category("5000 автомойка")

    assert groceries is not None
    assert groceries.category.code == "groceries"
    assert mobile is not None
    assert mobile.alias == "мобильная связь"
    assert mobile.category.code == "subscriptions_communications"
    assert not_home is None
    assert not_auto is None


@pytest.mark.asyncio
async def test_alias_service_ignores_dangerously_short_aliases(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        auto = await CategoryRepository(session).get_by_code("auto")
        assert auto is not None
        session.add(CategoryAliasModel(alias="то", category_id=auto.id))
        await session.flush()

        exact_short = await AliasService(session).resolve_category("то")
        embedded_short = await AliasService(session).resolve_category("что-то")

    assert exact_short is None
    assert embedded_short is None
