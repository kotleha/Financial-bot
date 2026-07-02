from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.categories import DEFAULT_CATEGORIES, DEFAULT_CATEGORY_ALIASES
from financial_bot.app.domain.types import CategoryOwnerRole, UserRole
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base, CategoryAliasModel, CategoryModel, UserModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/seed.sqlite3"
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
async def test_seed_initial_data_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        first_result = await seed_initial_data(session, settings)
        await session.commit()

    async with session_factory() as session:
        second_result = await seed_initial_data(session, settings)
        await session.commit()

        user_count = await session.scalar(select(func.count()).select_from(UserModel))
        category_count = await session.scalar(select(func.count()).select_from(CategoryModel))
        alias_count = await session.scalar(select(func.count()).select_from(CategoryAliasModel))

        assert first_result.users_created == 2
        assert first_result.categories_created == len(DEFAULT_CATEGORIES)
        assert first_result.aliases_created == len(DEFAULT_CATEGORY_ALIASES)
        assert second_result.users_created == 0
        assert second_result.categories_created == 0
        assert second_result.aliases_created == 0
        assert user_count == 2
        assert category_count == len(DEFAULT_CATEGORIES)
        assert alias_count == len(DEFAULT_CATEGORY_ALIASES)


@pytest.mark.asyncio
async def test_seed_assigns_shared_categories_and_internal_transfer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await session.commit()

        husband = await session.scalar(
            select(UserModel).where(UserModel.role == UserRole.HUSBAND.value)
        )
        wife = await session.scalar(select(UserModel).where(UserModel.role == UserRole.WIFE.value))
        groceries = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "groceries")
        )
        active_expense_categories = await session.scalars(
            select(CategoryModel)
            .where(CategoryModel.is_active.is_(True))
            .where(CategoryModel.is_expense.is_(True))
        )
        internal_transfer = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "internal_transfer")
        )
        income = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "income_general")
        )
        income_categories = await session.scalars(
            select(CategoryModel)
            .where(CategoryModel.code.like("income_%"))
            .order_by(CategoryModel.sort_order)
        )

        assert husband is not None
        assert wife is not None
        assert groceries is not None
        assert groceries.owner_user_id is None
        assert groceries.owner_role == CategoryOwnerRole.SYSTEM.value
        assert len(list(active_expense_categories)) == 18
        assert internal_transfer is not None
        assert internal_transfer.owner_user_id is None
        assert internal_transfer.owner_role == CategoryOwnerRole.SYSTEM.value
        assert internal_transfer.sort_order == 99
        assert not internal_transfer.is_expense
        assert income is not None
        assert income.owner_user_id is None
        assert income.owner_role == CategoryOwnerRole.SYSTEM.value
        assert income.sort_order == 100
        assert not income.is_expense
        assert [category.code for category in income_categories] == [
            "income_general",
            "income_salary",
            "income_advance",
            "income_bonus",
            "income_business",
            "income_debt_return",
            "income_other",
        ]


@pytest.mark.asyncio
async def test_seed_preserves_custom_category_titles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        groceries = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "groceries")
        )
        assert groceries is not None
        groceries.title = "Еда дома"
        await session.commit()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await session.commit()

        groceries = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "groceries")
        )
        assert groceries is not None
        assert groceries.title == "Еда дома"
