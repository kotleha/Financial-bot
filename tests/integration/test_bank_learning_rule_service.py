from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.services.bank_learning_rule_service import BankLearningRuleService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import BankCategoryRuleModel, Base
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/bank-learning-rules.sqlite3"
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
async def test_bank_learning_rules_are_scoped_to_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        await _add_rule(session, telegram_id=1001, merchant="MAGNIT", category_code="groceries")
        await _add_rule(
            session, telegram_id=1002, merchant="APTEKA", category_code="cosmetology_medicine"
        )
        await session.commit()

        husband_rules = await BankLearningRuleService(session).list_rules(telegram_user_id=1001)
        wife_rules = await BankLearningRuleService(session).list_rules(telegram_user_id=1002)

        assert [rule.merchant_display for rule in husband_rules] == ["MAGNIT"]
        assert husband_rules[0].category_title == "Продукты"
        assert [rule.merchant_display for rule in wife_rules] == ["APTEKA"]


@pytest.mark.asyncio
async def test_bank_learning_rule_status_and_category_can_be_changed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        rule = await _add_rule(
            session, telegram_id=1001, merchant="BAHETLE_P_QR", category_code="groceries"
        )
        restaurants = await CategoryRepository(session).get_by_code("restaurants_cafes")
        assert restaurants is not None
        await session.commit()

        service = BankLearningRuleService(session)
        disabled = await service.set_rule_active(
            rule_id=rule.id,
            telegram_user_id=1001,
            is_active=False,
        )
        updated = await service.update_rule_category(
            rule_id=rule.id,
            category_id=restaurants.id,
            telegram_user_id=1001,
        )
        details = await service.get_rule_details(rule_id=rule.id, telegram_user_id=1001)

        assert not disabled.is_active
        assert updated.old_category_title == "Продукты"
        assert updated.new_category_title == "Рестораны/Кафе"
        assert updated.is_active
        assert details.category_title == "Рестораны/Кафе"
        assert details.is_active


@pytest.mark.asyncio
async def test_bank_learning_rule_rejects_other_owner_and_service_category(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        rule = await _add_rule(
            session, telegram_id=1001, merchant="MAGNIT", category_code="groceries"
        )
        internal_transfer = await CategoryRepository(session).get_by_code("internal_transfer")
        assert internal_transfer is not None
        await session.commit()

        service = BankLearningRuleService(session)
        with pytest.raises(ValueError, match="не найдено"):
            await service.get_rule_details(rule_id=rule.id, telegram_user_id=1002)

        with pytest.raises(ValueError, match=r"недоступна|Служебную"):
            await service.update_rule_category(
                rule_id=rule.id,
                category_id=internal_transfer.id,
                telegram_user_id=1001,
            )


async def _add_rule(
    session: AsyncSession,
    *,
    telegram_id: int,
    merchant: str,
    category_code: str,
) -> BankCategoryRuleModel:
    user = await UserRepository(session).get_by_telegram_id(telegram_id)
    category = await CategoryRepository(session).get_by_code(category_code)
    assert user is not None
    assert category is not None

    rule = BankCategoryRuleModel(
        owner_user_id=user.id,
        bank="sber",
        merchant_key=merchant.lower(),
        merchant_display=merchant,
        category_id=category.id,
        hit_count=2,
        is_active=True,
        last_confirmed_at=datetime(2026, 6, 27, 12, 0),
    )
    session.add(rule)
    await session.flush()
    return rule
