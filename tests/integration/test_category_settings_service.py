from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.services.alias_service import AliasService
from financial_bot.app.services.category_settings_service import CategorySettingsService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/category-settings.sqlite3"
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
async def test_category_settings_lists_active_expense_categories(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        await session.commit()

        lines = await CategorySettingsService(session).list_categories()
        groceries = next(line for line in lines if line.code == "groceries")

        assert len(lines) == 17
        assert groceries.title == "Продукты"
        assert groceries.sort_order == 2
        assert groceries.alias_count > 0
        assert all(line.code != "internal_transfer" for line in lines)


@pytest.mark.asyncio
async def test_category_rename_preserves_code_and_sort_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        await session.commit()

        result = await CategorySettingsService(session).rename_category(
            category_code="groceries",
            new_title="Еда дома",
        )
        await session.commit()
        details = await CategorySettingsService(session).get_category_details("groceries")

        assert result.old_title == "Продукты"
        assert result.new_title == "Еда дома"
        assert result.code == "groceries"
        assert result.sort_order == 2
        assert details is not None
        assert details.title == "Еда дома"
        assert details.sort_order == 2


@pytest.mark.asyncio
async def test_added_alias_is_normalized_and_used_by_alias_service(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        await session.commit()

        result = await CategorySettingsService(session).add_alias(
            category_code="groceries",
            alias="  Bahetle   P QR  ",
        )
        match = await AliasService(session).resolve_category("3500 bahetle p qr")

        assert result.alias == "bahetle p qr"
        assert match is not None
        assert match.alias == "bahetle p qr"
        assert match.category.code == "groceries"


@pytest.mark.asyncio
async def test_alias_conflicts_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        await session.commit()
        service = CategorySettingsService(session)

        with pytest.raises(ValueError, match="уже есть"):
            await service.add_alias(category_code="groceries", alias="магнит")

        with pytest.raises(ValueError, match="уже занят"):
            await service.add_alias(category_code="auto", alias="магнит")


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["", " ", "а", "7", "99", "***"])
async def test_dangerous_aliases_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    alias: str,
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        await session.commit()

        with pytest.raises(ValueError):
            await CategorySettingsService(session).add_alias(
                category_code="groceries",
                alias=alias,
            )
