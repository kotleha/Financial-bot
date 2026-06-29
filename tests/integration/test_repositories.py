from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.domain.types import (
    CategoryOwnerRole,
    TransactionSource,
    TransactionType,
    UserRole,
)
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import (
    Base,
    CategoryAliasModel,
    CategoryModel,
    TransactionModel,
    UserModel,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.transaction_repository import TransactionRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/test.sqlite3"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repositories_create_and_query_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        users = UserRepository(session)
        categories = CategoryRepository(session)
        transactions = TransactionRepository(session)

        husband = await users.add(
            UserModel(
                telegram_id=1001,
                name="Husband",
                role=UserRole.HUSBAND.value,
            )
        )
        await users.add(
            UserModel(
                telegram_id=1002,
                name="Wife",
                role=UserRole.WIFE.value,
            )
        )
        groceries = await categories.add(
            CategoryModel(
                code="groceries",
                title="Groceries",
                owner_user_id=None,
                owner_role=CategoryOwnerRole.SYSTEM.value,
                sort_order=2,
            )
        )
        await categories.add_alias(CategoryAliasModel(alias="groceries", category_id=groceries.id))
        await transactions.add(
            TransactionModel(
                amount=350000,
                currency="RUB",
                occurred_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                payer_user_id=husband.id,
                category_id=groceries.id,
                type=TransactionType.EXPENSE.value,
                source=TransactionSource.CARD.value,
                raw_text="3500 groceries",
                included_in_reports=True,
                created_by_user_id=husband.id,
            )
        )
        await session.commit()

    async with session_factory() as session:
        users = UserRepository(session)
        categories = CategoryRepository(session)
        transactions = TransactionRepository(session)

        found_husband = await users.get_by_telegram_id(1001)
        found_category = await categories.get_by_alias("groceries")
        period_transactions = await transactions.list_for_period(
            datetime(2026, 6, 1, tzinfo=UTC),
            datetime(2026, 7, 1, tzinfo=UTC),
        )

        assert found_husband is not None
        assert found_husband.role == UserRole.HUSBAND.value
        assert found_category is not None
        assert found_category.code == "groceries"
        assert len(period_transactions) == 1
        assert period_transactions[0].amount == 350000
